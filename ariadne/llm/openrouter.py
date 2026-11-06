from __future__ import annotations

import copy
import math

from ariadne._util import dumps, loads
from ariadne.errors import Error
from .model import Message, ToolCall, Response, Usage, Role
from .gateway import deliver
from .transport import NativeHttpTransport, HttpRequest, Headers, Data


def protocol(message):
    return Error("PROTOCOL_ERROR", message)


def status_error(status):
    code, message, retryable = {
        401: ("AUTHENTICATION_ERROR", "OpenRouter rejected the credentials", False),
        403: ("AUTHENTICATION_ERROR", "OpenRouter rejected the credentials", False),
        402: ("PAYMENT_REQUIRED", "OpenRouter account has insufficient credits", False),
        429: ("RATE_LIMITED", "OpenRouter rate limit reached", True),
        408: ("TIMEOUT", "OpenRouter request timed out", True),
        504: ("TIMEOUT", "OpenRouter request timed out", True),
        400: ("PROVIDER_REQUEST_ERROR", "OpenRouter rejected the model or request parameters", False),
        404: ("PROVIDER_REQUEST_ERROR", "OpenRouter rejected the model or request parameters", False),
        422: ("PROVIDER_REQUEST_ERROR", "OpenRouter rejected the model or request parameters", False),
    }.get(status, ("PROVIDER_ERROR", f"OpenRouter returned HTTP {status}", True))
    return Error(code, message, retryable)


def encode_message(message):
    result = {"role": message.role, "content": message.content}
    if message.tool_calls:
        result["tool_calls"] = [{"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}} for call in message.tool_calls]
    if message.tool_call_id is not None:
        result["tool_call_id"] = message.tool_call_id
    for key in ("reasoning", "reasoning_details"):
        if key in message.continuation:
            result[key] = copy.deepcopy(message.continuation[key])
    return result


class OpenRouter:
    def __init__(self, transport=None):
        self.transport = transport or NativeHttpTransport()

    async def generate(self, binding, request, credentials, cancellation, emit):
        body = {"model": binding.model, "messages": [encode_message(m) for m in request.messages], "stream": True,
                "stream_options": {"include_usage": True}, "max_tokens": binding.settings.get("max_output_tokens", 2048),
                "provider": {"require_parameters": True, "allow_fallbacks": False}}
        for key in ("temperature", "top_p"):
            if key in binding.settings:
                body[key] = binding.settings[key]
        if request.tools:
            body["tools"] = [{"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.input_schema}} for tool in request.tools]
            body["tool_choice"] = "auto"
        http = HttpRequest(binding.provider.base_url.rstrip("/") + "/chat/completions", credentials.resolve(binding.provider.credential_ref), dumps(body).encode("utf-8"), binding.timeout_ms)
        parser, got_headers = StreamParser(), False
        stream = self.transport.post(http, cancellation)
        try:
            async for packet in stream:
                cancellation.check()
                if isinstance(packet, Headers):
                    if got_headers:
                        raise protocol("Unexpected repeated HTTP headers")
                    got_headers = True
                    if packet.status != 200:
                        raise status_error(packet.status)
                    if packet.content_type.split(";", 1)[0].strip().lower() != "text/event-stream":
                        raise protocol("Expected an SSE response from OpenRouter")
                elif isinstance(packet, Data):
                    if not got_headers:
                        raise protocol("Body arrived before HTTP headers")
                    for event in parser.feed(packet.data):
                        await deliver(emit, event)
                else:
                    raise protocol("Unknown HTTP transport event")
        finally:
            close = getattr(stream, "aclose", None)
            if close:
                await close()
        response = parser.finish()
        for call in response.message.tool_calls:
            await deliver(emit, {"type": "tool_call_ready", "call": call.to_dict()})
        return response


class StreamParser:
    """SSE framing and OpenRouter deltas; tool calls are usable only after finish."""

    def __init__(self):
        self.buffer, self.data, self.total, self.done, self.first_line = bytearray(), [], 0, False, True
        self.response = Response(Message(Role.ASSISTANT, ""), "")
        self.calls = {}

    def feed(self, chunk):
        self.total += len(chunk)
        if self.total > 16 * 1024 * 1024:
            raise protocol("Model response exceeded 16 MiB")
        self.buffer.extend(chunk)
        events = []
        while (end := self.buffer.find(b"\n")) >= 0:
            raw = bytes(self.buffer[:end + 1])
            del self.buffer[:end + 1]
            try:
                line = raw.decode("utf-8").rstrip("\r\n")
            except UnicodeError as exc:
                raise protocol("Invalid UTF-8 in SSE stream") from exc
            if self.first_line:
                line, self.first_line = line.removeprefix("\ufeff"), False
            if not line:
                events.extend(self._dispatch())
            elif line.startswith("data:"):
                self.data.append(line[5:].removeprefix(" "))
        return events

    def _dispatch(self):
        if not self.data:
            return []
        raw = "\n".join(self.data)
        self.data.clear()
        if self.done:
            raise protocol("Unexpected data after stream completion")
        if raw == "[DONE]":
            self.done = True
            return []
        try:
            value = loads(raw)
        except Error as exc:
            raise protocol("Invalid JSON in SSE event") from exc
        if not isinstance(value, dict):
            raise protocol("SSE event must be an object")
        if "error" in value:
            error = value["error"]
            code = error.get("code") if isinstance(error, dict) else None
            raise status_error(code) if type(code) is int else Error("PROVIDER_ERROR", "OpenRouter failed during generation")
        events = []
        if isinstance(value.get("id"), str):
            self.response.provider_request_id = value["id"]
        if isinstance(value.get("model"), str):
            self.response.model = value["model"]
        if isinstance(value.get("usage"), dict):
            raw_usage = value["usage"]
            counts = [raw_usage.get(k) for k in ("prompt_tokens", "completion_tokens")]
            if any(v is not None and (type(v) is not int or v < 0) for v in counts):
                raise protocol("Invalid usage measurements")
            cost = raw_usage.get("cost")
            if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
                raise protocol("Invalid reported cost")
            self.response.usage = Usage(*counts, cost)
            events.append({"type": "usage", "usage": self.response.usage.to_dict()})
        choices = value.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise protocol("Expected a single completion choice")
        if not choices:
            return events
        choice = choices[0]
        if not isinstance(choice, dict):
            raise protocol("Invalid completion choice")
        reason = choice.get("finish_reason")
        if reason is not None:
            if reason == "error":
                raise Error("PROVIDER_ERROR", "OpenRouter failed during generation")
            if not isinstance(reason, str) or self.response.finish_reason:
                raise protocol("Invalid or repeated finish reason")
            self.response.finish_reason = reason
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            raise protocol("Invalid completion delta")
        for key in ("content", "refusal"):
            value = delta.get(key)
            if value is not None:
                if not isinstance(value, str):
                    raise protocol("Only text responses are supported")
                self.response.message.content += value
                events.append({"type": "text_delta", "text": value})
        continuation = self.response.message.continuation
        if delta.get("reasoning") is not None:
            if not isinstance(delta["reasoning"], str):
                raise protocol("Invalid reasoning metadata")
            continuation["reasoning"] = continuation.get("reasoning", "") + delta["reasoning"]
        if delta.get("reasoning_details") is not None:
            if not isinstance(delta["reasoning_details"], list):
                raise protocol("Invalid reasoning continuation data")
            continuation.setdefault("reasoning_details", []).extend(copy.deepcopy(delta["reasoning_details"]))
        calls = delta.get("tool_calls") or []
        if not isinstance(calls, list):
            raise protocol("Invalid tool-call delta")
        for call in calls:
            if not isinstance(call, dict) or type(call.get("index")) is not int or not 0 <= call["index"] < 32 or call.get("type", "function") != "function":
                raise protocol("Invalid tool-call index or type")
            partial = self.calls.setdefault(call["index"], {"id": "", "name": "", "arguments": ""})
            function = call.get("function") or {}
            if not isinstance(function, dict):
                raise protocol("Invalid function-call delta")
            for key, value in (("id", call.get("id")), ("name", function.get("name")), ("arguments", function.get("arguments"))):
                if value is not None:
                    if not isinstance(value, str):
                        raise protocol("Tool-call fields must be strings")
                    partial[key] += value
        return events

    def finish(self):
        if not self.done or not self.response.finish_reason or self.buffer or self.data:
            raise protocol("Model stream ended without a complete terminal event")
        ids = set()
        for _, call in sorted(self.calls.items()):
            if self.response.finish_reason != "tool_calls" or not call["id"] or not call["name"] or call["id"] in ids:
                raise protocol("Incomplete, duplicate, or truncated tool call")
            ids.add(call["id"])
            try:
                arguments = loads(call["arguments"])
            except Error as exc:
                raise protocol("Tool arguments are not complete JSON") from exc
            if not isinstance(arguments, dict):
                raise protocol("Tool arguments must be an object")
            self.response.message.tool_calls.append(ToolCall(**call))
        if self.response.finish_reason == "tool_calls" and not self.calls:
            raise protocol("Tool-call completion contains no calls")
        if self.response.message.content == "":
            self.response.message.content = None
        return self.response
