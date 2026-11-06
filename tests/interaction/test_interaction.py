import asyncio

from ariadne.errors import Error
from ariadne.interaction import Interface, Source, EventContext
from tests.support import AsyncCase


class InteractionTests(AsyncCase):
    async def test_parallel_publishers_have_session_order_and_independent_sources(self):
        interface = Interface(32)
        self.addAsyncCleanup(interface.close)
        async with interface.subscribe("a") as a, interface.subscribe("b") as b:
            async def publisher(source):
                for _ in range(5):
                    await interface.publish("a", Source("tool", source), EventContext(task_id="task"), {"type": "activity_updated", "label": source, "state": "running"})
            await asyncio.gather(*(publisher(str(i)) for i in range(4)))
            await interface.publish("b", Source("agent", "other"), EventContext(), {"type": "run_finished", "outcome": "completed"})
            events = [await a.recv() for _ in range(20)]
            self.assertEqual([e.sequence for e in events], list(range(1, 21)))
            self.assertEqual({e.source.instance_id for e in events}, {"0", "1", "2", "3"})
            self.assertEqual((await b.recv()).sequence, 1)
            self.assertTrue(all(e.context.task_id == "task" for e in events))

    async def test_backpressure_releases_on_disconnect_without_blocking_other_sessions(self):
        interface = Interface(1)
        self.addAsyncCleanup(interface.close)
        a, b = interface.subscribe("a"), interface.subscribe("b")
        self.addAsyncCleanup(b.close)
        payload = {"type": "run_finished", "outcome": "completed"}
        await interface.publish("a", Source("agent", "one"), EventContext(), payload)
        blocked = asyncio.create_task(interface.publish("a", Source("tool", "two"), EventContext(), payload))
        await asyncio.sleep(0)
        self.assertFalse(blocked.done())
        await interface.publish("b", Source("agent", "other"), EventContext(), payload)
        self.assertEqual((await b.recv()).session_id, "b")
        await a.close()
        await self.assert_async_code("NO_SUBSCRIBER", blocked)
        async with interface.subscribe("a") as fresh:
            await interface.publish("a", Source("agent", "new"), EventContext(), payload)
            self.assertGreater((await fresh.recv()).sequence, 1)

    async def test_command_validation_queue_limits_and_single_subscriber(self):
        interface = Interface(1)
        self.addAsyncCleanup(interface.close)
        async with interface.subscribe("session"):
            with self.assertRaises(Error) as raised: interface.subscribe("session")
            self.assertEqual(raised.exception.code, "ALREADY_SUBSCRIBED")
            command_id = interface.submit("session", {"type": "send_message", "text": "hello"})
            with self.assertRaises(Error) as raised: interface.submit("session", {"type": "send_message", "text": "full"})
            self.assertEqual(raised.exception.code, "BUSY")
            self.assertEqual((await interface.receive_command()).command_id, command_id)
            for payload in [{"type": "send_message", "text": " "}, {"type": "cancel_run", "run_id": ""}, {"type": "send_message", "text": "x", "unknown": 1}]:
                with self.assertRaises(Error): interface.submit("session", payload)

    async def test_interface_close_wakes_waiting_command_and_event_consumers(self):
        interface = Interface()
        subscription = interface.subscribe("session")
        command = asyncio.create_task(interface.receive_command())
        event = asyncio.create_task(subscription.recv())
        await asyncio.sleep(0)
        await interface.close()
        await self.assert_async_code("DISCONNECTED", command)
        await self.assert_async_code("DISCONNECTED", event)
