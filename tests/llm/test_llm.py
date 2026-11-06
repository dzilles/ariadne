import asyncio
import copy
import json
from unittest.mock import patch

from ariadne.errors import Error
from ariadne.configuration import Provider
from ariadne.llm import (Binding, CallContext, Request, Message, Gateway, OpenRouter, Cancellation,
                         EnvironmentCredentials, Headers, Data)
from ariadne._util import dumps
from tests.support import AsyncCase, Credentials


def event(value):
    return f"data: {dumps(value)}\r\n\r\n"


def text_stream(value="héllo 🌍"):
    return (event({"id": "generation", "model": "example/model", "choices": [{"delta": {"content": value}}]})
            + event({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 3, "cost": 0.01}}) + "data: [DONE]\n\n")


def binding():
    return Binding(Provider("api", "openrouter", "https://openrouter.ai/api/v1", "env:KEY"), "example/model", "snapshot")


def context(caller="orchestrator"):
    return CallContext("call-" + caller, caller, "snapshot", parent_call_id="parent")


class MockTransport:
    def __init__(self, stream, status=200):
        self.stream, self.status, self.requests, self.closed = stream, status, [], False

    async def post(self, request, cancellation):
        self.requests.append(request)
        try:
            yield Headers(self.status, "text/event-stream; charset=utf-8")
            for byte in self.stream.encode("utf-8"):
                cancellation.check()
                await asyncio.sleep(0)
                yield Data(bytes([byte]))
        finally:
            self.closed = True


class LlmTests(AsyncCase):
    def setup_gateway(self, stream, status=200):
        transport = MockTransport(stream, status)
        gateway = Gateway(Credentials())
        gateway.register_adapter("openrouter", OpenRouter(transport))
        return gateway, transport

    async def test_fragmented_unicode_comments_usage_and_context(self):
        gateway, transport = self.setup_gateway(": keepalive\r\n\r\n" + text_stream())
        events = []
        response = await gateway.generate(binding(), Request([Message.text("user", "hello")]), context(), emit=events.append)
        self.assertEqual(response.message.content, "héllo 🌍")
        self.assertEqual(response.usage.input_tokens, 5)
        self.assertEqual(response.usage.cost, 0.01)
        self.assertEqual([events[0]["type"], events[-1]["type"]], ["started", "finished"])
        self.assertTrue(all(e["context"]["parent_call_id"] == "parent" for e in events))
        body = json.loads(transport.requests[0].body)
        self.assertTrue(body["provider"]["require_parameters"])
        self.assertFalse(body["provider"]["allow_fallbacks"])
        self.assertNotIn("test-secret", transport.requests[0].body.decode())
        self.assertTrue(transport.closed)

    async def test_fragmented_tool_arguments_and_opaque_continuation_survive_next_call(self):
        stream = (event({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "tool", "type": "function", "function": {"name": "get_task", "arguments": '{"id":'}}], "reasoning_details": [{"type": "reasoning.encrypted", "data": "opaque", "index": 0}]}}]})
                  + event({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"abc"}'}}]}}]})
                  + event({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}) + "data: [DONE]\n\n")
        gateway, transport = self.setup_gateway(stream)
        events = []
        request = Request([Message.text("user", "get it")])
        response = await gateway.generate(binding(), request, context(), emit=events.append)
        self.assertEqual(response.message.tool_calls[0].arguments, '{"id":"abc"}')
        self.assertEqual(sum(e["type"] == "tool_call_ready" for e in events), 1)
        self.assertFalse(any(e["type"] == "text_delta" for e in events))
        request.messages.extend([response.message, Message.tool("tool", {"ok": True})])
        await gateway.generate(binding(), request, context())
        body = json.loads(transport.requests[1].body)
        self.assertEqual(body["messages"][1]["reasoning_details"][0]["data"], "opaque")
        self.assertEqual(body["messages"][2]["tool_call_id"], "tool")

    async def test_partial_invalid_and_midstream_error_responses_never_publish_ready_tools(self):
        invalid = ["data: {invalid}\n\n", event({"choices": [{"delta": {"content": "partial"}, "finish_reason": "stop"}]}),
                   event({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "tool", "function": {"name": "create_task", "arguments": "{"}}]}, "finish_reason": "tool_calls"}]}) + "data: [DONE]\n\n",
                   event({"choices": [{"delta": {"content": "partial"}}]}) + event({"error": {"code": 503, "message": "test-secret must not leak"}})]
        for stream in invalid:
            gateway, transport = self.setup_gateway(stream)
            events = []
            with self.assertRaises(Error) as raised:
                await gateway.generate(binding(), Request([Message.text("user", "hello")]), context(), emit=events.append)
            self.assertNotIn("test-secret", str(raised.exception))
            self.assertEqual(events[-1]["type"], "failed")
            self.assertFalse(any(e["type"] in ("tool_call_ready", "finished") for e in events))
            self.assertTrue(transport.closed)

    async def test_http_errors_missing_credentials_and_unknown_adapters(self):
        for status, code in [(401, "AUTHENTICATION_ERROR"), (402, "PAYMENT_REQUIRED"), (429, "RATE_LIMITED"), (503, "PROVIDER_ERROR")]:
            gateway, transport = self.setup_gateway("", status)
            await self.assert_async_code(code, gateway.generate(binding(), Request([Message.text("user", "hello")]), context()))
            self.assertTrue(transport.closed)
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(Error) as raised: EnvironmentCredentials().resolve("env:KEY")
            self.assertEqual(raised.exception.code, "AUTHENTICATION_ERROR")
        selected = binding()
        selected.provider.adapter = "other"
        await self.assert_async_code("UNSUPPORTED_ADAPTER", Gateway(Credentials()).generate(selected, Request([Message.text("user", "hello")]), context()))

    async def test_cancellation_prevents_requests_and_interrupts_a_stream(self):
        gateway, transport = self.setup_gateway(text_stream())
        cancellation = Cancellation()
        cancellation.cancel()
        await self.assert_async_code("CANCELLED", gateway.generate(binding(), Request([Message.text("user", "hello")]), context(), cancellation))
        self.assertEqual(transport.requests, [])
        cancellation = Cancellation()
        async def emit(value):
            if value["type"] == "text_delta": cancellation.cancel()
        await self.assert_async_code("CANCELLED", gateway.generate(binding(), Request([Message.text("user", "hello")]), context(), cancellation, emit))
        self.assertTrue(transport.closed)

    async def test_concurrent_callers_do_not_share_context_or_inputs(self):
        class Echo:
            async def post(self, request, cancellation):
                body = json.loads(request.body)
                yield Headers(200, "text/event-stream")
                for chunk in text_stream(body["model"] + ":" + body["messages"][0]["content"]).encode():
                    await asyncio.sleep(0)
                    yield Data(bytes([chunk]))
        gateway = Gateway(Credentials())
        gateway.register_adapter("openrouter", OpenRouter(Echo()))
        async def call(caller):
            selected = binding()
            selected.model = "example/" + caller
            events = []
            result = await gateway.generate(selected, Request([Message.text("user", caller)]), context(caller), emit=events.append)
            self.assertEqual(result.message.content, f"example/{caller}:{caller}")
            self.assertTrue(all(e["context"]["caller_id"] == caller for e in events))
        await asyncio.gather(*(call(caller) for caller in ["orchestrator", "agent", "nested-tool"]))
