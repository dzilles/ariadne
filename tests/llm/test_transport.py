import asyncio
import threading
from unittest.mock import patch

from ariadne.llm import NativeHttpTransport, HttpRequest, Cancellation, Data, Headers
from tests.support import AsyncCase


class FakeSocket:
    def __init__(self, stop): self.stop = stop
    def shutdown(self, *_): self.stop.set()


class FakeResponse:
    status = 200
    def __init__(self, connection): self.connection, self.chunks = connection, iter([b"data: one\n\n", b"data: [DONE]\n\n"])
    def getheader(self, name, default): return "text/event-stream"
    def read1(self, count):
        if self.connection.stall:
            self.connection.reading.set()
            self.connection.stop.wait(2)
            return b""
        return next(self.chunks, b"")


class FakeConnection:
    def __init__(self, *, stall=False, timeout=False):
        self.stall, self.timeout = stall, timeout
        self.stop, self.reading, self.closed = threading.Event(), threading.Event(), threading.Event()
        self.sock, self.requests = FakeSocket(self.stop), []
    def connect(self):
        if self.timeout: raise TimeoutError("details should not leak")
    def request(self, method, path, *, body, headers): self.requests.append((method, path, body, headers))
    def getresponse(self): return FakeResponse(self)
    def close(self): self.stop.set(); self.closed.set()


class NativeTransportTests(AsyncCase):
    async def wait_event(self, event, timeout=0.5):
        async def poll():
            while not event.is_set():
                await asyncio.sleep(0.005)
            return True
        return await asyncio.wait_for(poll(), timeout)
    def request(self, timeout=500):
        return HttpRequest("https://openrouter.ai/api/v1/chat/completions", "test-secret", b'{"model":"example/model"}', timeout)

    async def test_native_transport_streams_bytes_without_subprocesses(self):
        connection = FakeConnection()
        with patch("ariadne.llm.transport.http.client.HTTPSConnection", return_value=connection):
            packets = [packet async for packet in NativeHttpTransport().post(self.request(), Cancellation())]
        self.assertIsInstance(packets[0], Headers)
        self.assertEqual(b"".join(p.data for p in packets if isinstance(p, Data)), b"data: one\n\ndata: [DONE]\n\n")
        self.assertEqual(connection.requests[0][3]["Authorization"], "Bearer test-secret")
        self.assertNotIn("test-secret", connection.requests[0][2].decode())
        self.assertTrue(await self.wait_event(connection.closed))

    async def test_cancellation_closes_a_blocked_read(self):
        connection, cancellation = FakeConnection(stall=True), Cancellation()
        async def consume():
            return [packet async for packet in NativeHttpTransport().post(self.request(2000), cancellation)]
        with patch("ariadne.llm.transport.http.client.HTTPSConnection", return_value=connection):
            pending = asyncio.create_task(consume())
            self.assertTrue(await self.wait_event(connection.reading))
            cancellation.cancel()
            await self.assert_async_code("CANCELLED", asyncio.wait_for(pending, 0.5))
            self.assertTrue(await self.wait_event(connection.closed))

    async def test_overall_deadline_and_connect_timeouts_are_normalized(self):
        for connection in (FakeConnection(stall=True), FakeConnection(timeout=True)):
            async def consume():
                return [packet async for packet in NativeHttpTransport().post(self.request(40), Cancellation())]
            with patch("ariadne.llm.transport.http.client.HTTPSConnection", return_value=connection):
                await self.assert_async_code("TIMEOUT", consume())
                self.assertTrue(await self.wait_event(connection.closed))
