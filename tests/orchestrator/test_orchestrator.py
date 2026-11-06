import asyncio
import copy

from ariadne.errors import Error
from ariadne._util import new_id
from ariadne.interaction import Interface
from ariadne.llm import Message, ToolCall, Cancellation, Gateway
from ariadne.orchestrator import ConversationStore, Entry, State, TaskTools, Application, initialize
from ariadne.task import TaskStore, SearchQuery
from tests.support import AsyncCase, Harness, Script, calls, reply, Credentials


class OrchestratorTests(AsyncCase):
    def setUp(self):
        super().setUp()
        self.harness = Harness(self.root)
        self.conversation = self.harness.conversation()
        self.interface = Interface(64)
        self.addAsyncCleanup(self.interface.close)

    async def turn(self, script, text="hello", session=None):
        return await self.harness.engine().turn(session or self.conversation.id, new_id("command"), text, script.gateway(), self.interface)

    async def test_real_task_writes_and_orchestrator_tool_dialogue_survive_restart(self):
        script = Script(calls(("create-1", "create_task", {"description": "Implement Python streaming", "tags": ["python"]})), reply("Created the task."))
        async with self.interface.subscribe(self.conversation.id) as events:
            await self.turn(script, "Create a streaming task")
            observed = []
            while True:
                event = await asyncio.wait_for(events.recv(), 1)
                observed.append(event)
                if event.payload["type"] == "run_finished": break
        saved = self.harness.saved(self.conversation.id)
        self.assertEqual(saved.state, State.IDLE)
        self.assertEqual(len(saved.entries), 5)
        self.assertEqual(script.requests[1][1].messages[-1].role, "tool")
        with TaskStore(self.harness.task_path) as store:
            tasks = store.orchestrator().search_tasks(SearchQuery("project"))
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].status, "draft")
        self.assertEqual(sum(e.payload["type"] == "run_finished" for e in observed), 1)
        self.assertTrue(all("project_id" not in tool.input_schema["properties"] for tool in script.requests[0][1].tools))

    async def test_snapshots_and_independent_conversations_keep_context_separate(self):
        profile = self.harness.config.get_profile("orchestrator")
        profile.model = "example/new-model"
        self.harness.config.save_profile(profile)
        newer = self.harness.conversation()
        script = Script(reply("first"), reply("second"), reply("new"))
        await self.turn(script, "Remember apples")
        await self.turn(script, "What did I say?")
        await self.turn(script, "hello", newer.id)
        self.assertEqual(script.requests[0][0].model, "example/model")
        self.assertEqual(script.requests[2][0].model, "example/new-model")
        self.assertTrue(any(m.content == "Remember apples" for m in script.requests[1][1].messages))
        self.assertFalse(any(m.content == "Remember apples" for m in script.requests[2][1].messages))

    async def test_model_failure_retains_user_message_and_no_partial_reply(self):
        await self.assert_async_code("RATE_LIMITED", self.turn(Script(Error("RATE_LIMITED", "Try later"))))
        saved = self.harness.saved(self.conversation.id)
        self.assertEqual(saved.state, State.FAILED)
        self.assertEqual(len(saved.entries), 2)
        self.assertEqual(saved.last_error["code"], "RATE_LIMITED")

    async def test_project_scoping_internal_roles_and_config_edits_are_enforced(self):
        with TaskStore(self.harness.task_path) as store:
            other = store.orchestrator().create_task("other", "Private task")
            tools = TaskTools(store, self.harness.config.load()[1], "project")
            for name in ("get_task", "update_task", "get_history"):
                with self.assertRaises(Error) as raised: tools.call(name, {"id": other.id})
                self.assertEqual(raised.exception.code, "FORBIDDEN")
            for name in ("record_event", "index_pending", "save_profile", "run_command"):
                with self.assertRaises(Error) as raised: tools.call(name, {})
                self.assertEqual(raised.exception.code, "FORBIDDEN")
            with self.assertRaises(Error): tools.call("create_task", {"project_id": "other", "description": "escape"})

    async def test_tool_limits_close_unexecuted_calls_without_extra_side_effects(self):
        profile = self.harness.config.get_profile("orchestrator")
        profile.settings["max_tool_calls"] = 1
        self.harness.config.save_profile(profile)
        session = self.harness.conversation()
        script = Script(calls(("first", "create_task", {"description": "First"}), ("second", "create_task", {"description": "Second"})))
        await self.assert_async_code("TOOL_LIMIT", self.turn(script, session=session.id))
        saved = self.harness.saved(session.id)
        self.assertEqual(saved.entries[-1].message.tool_call_id, "second")
        with TaskStore(self.harness.task_path) as store:
            self.assertEqual(len(store.orchestrator().search_tasks(SearchQuery("project"))), 1)

    async def test_crash_recovery_does_not_replay_ambiguous_tool_calls(self):
        with TaskStore(self.harness.task_path) as store:
            store.orchestrator().create_task("project", "Already written before interruption")
        conversation = copy.deepcopy(self.conversation)
        conversation.state, conversation.active_run_id = State.RUNNING, "old-run"
        conversation.entries.append(Entry(new_id(), Message("assistant", tool_calls=[ToolCall("pending", "create_task", '{"description":"Already written before interruption"}')])))
        with ConversationStore(self.harness.conversation_path) as store:
            store.save(conversation)
            self.assertEqual(store.recover_interrupted(), 1)
            self.assertEqual(store.recover_interrupted(), 0)
        saved = self.harness.saved(conversation.id)
        self.assertEqual(saved.state, State.INTERRUPTED)
        self.assertEqual(saved.entries[-1].message.tool_call_id, "pending")
        await self.turn(Script(reply("I can inspect the task before proceeding.")))
        with TaskStore(self.harness.task_path) as store:
            self.assertEqual(len(store.orchestrator().search_tasks(SearchQuery("project"))), 1)

    async def test_conversation_version_checks_and_public_view_hide_private_context(self):
        with ConversationStore(self.harness.conversation_path) as store:
            first, stale = store.get(self.conversation.id), store.get(self.conversation.id)
            first.title = "Changed"
            first.entries.append(Entry(new_id(), Message("assistant", "Visible", continuation={"reasoning": "PRIVATE-REASONING"})))
            store.save(first)
            with self.assertRaises(Error) as raised: store.save(stale)
            self.assertEqual(raised.exception.code, "VERSION_CONFLICT")
            public = str(store.get(first.id).view())
            self.assertIn("Visible", public)
            self.assertNotIn("PRIVATE-REASONING", public)
            self.assertNotIn("You are Ariadne", public)


class ApplicationTests(AsyncCase):
    def setUp(self):
        super().setUp()
        self.harness = Harness(self.root)

    async def test_dispatch_cancellation_and_exclusive_application_lock(self):
        ready = asyncio.Event()
        class Stall:
            async def generate(self, binding, request, credentials, cancellation, emit):
                ready.set()
                await cancellation.wait()
                cancellation.check()
        gateway = Gateway(Credentials())
        gateway.register_adapter("openrouter", Stall())
        async with await Application.start(self.harness.options(), gateway) as app:
            await self.assert_async_code("APPLICATION_BUSY", Application.start(self.harness.options(), gateway))
            session = app.create_conversation()
            async with app.interface.subscribe(session.id) as events:
                run_id = app.submit(session.id, {"type": "send_message", "text": "hello"})
                await asyncio.wait_for(ready.wait(), 1)
                app.submit(session.id, {"type": "cancel_run", "run_id": run_id})
                while True:
                    event = await asyncio.wait_for(events.recv(), 1)
                    if event.payload["type"] == "run_finished":
                        self.assertEqual(event.payload["outcome"], "cancelled")
                        break
            self.assertEqual(app.conversation(session.id).last_error["code"], "CANCELLED")

    async def test_direct_interface_commands_cannot_bypass_project_scope(self):
        async with await Application.start(self.harness.options(), Script(reply()).gateway()) as app:
            with ConversationStore(self.harness.config.root / "orchestrator.sqlite") as store:
                other = store.create(self.harness.config, "other", project_summary="Other")
            async with app.interface.subscribe(other.id) as events:
                app.interface.submit(other.id, {"type": "send_message", "text": "hello"})
                event = await asyncio.wait_for(events.recv(), 1)
                self.assertEqual(event.payload["error"]["code"], "FORBIDDEN")

    async def test_initializer_refuses_overwrite_and_shutdown_releases_lock(self):
        with self.assertRaises(Error) as raised: initialize(self.harness.config.root, "different/model")
        self.assertEqual(raised.exception.code, "VERSION_CONFLICT")
        app = await Application.start(self.harness.options(), Script(reply()).gateway())
        await app.close()
        async with await Application.start(self.harness.options(), Script(reply()).gateway()):
            pass
