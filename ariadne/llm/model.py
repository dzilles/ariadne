from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from enum import StrEnum
import threading

from ariadne._util import JsonModel, text
from ariadne.errors import Error
from ariadne.configuration import Provider, Snapshot


class Cancellation:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    def is_cancelled(self):
        return self._event.is_set()

    def check(self):
        if self.is_cancelled():
            raise Error("CANCELLED", "Model request cancelled")

    async def wait(self):
        while not self.is_cancelled():
            await asyncio.sleep(0.02)


@dataclass
class Binding(JsonModel):
    provider: Provider
    model: str
    snapshot_id: str
    settings: dict = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.provider, dict):
            self.provider = Provider.from_dict(self.provider)

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot, profile_id: str):
        snapshot.configuration.validate()
        profile = snapshot.configuration.profiles.get(profile_id)
        if profile is None:
            raise Error("NOT_FOUND", "LLM profile does not exist")
        provider = snapshot.configuration.providers.get(profile.provider_id)
        if provider is None or profile.model is None:
            raise Error.invalid("Profile needs an explicit API connection, provider_id, and model")
        return cls(copy.deepcopy(provider), profile.model, snapshot.id, copy.deepcopy(profile.settings))

    @property
    def timeout_ms(self):
        return self.settings.get("timeout_ms", 120000)


@dataclass
class CallContext(JsonModel):
    call_id: str
    caller_id: str
    snapshot_id: str
    session_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    parent_call_id: str | None = None


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall(JsonModel):
    id: str
    name: str
    arguments: str


@dataclass
class Message(JsonModel):
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    continuation: dict = field(default_factory=dict)

    def __post_init__(self):
        from ariadne._util import enum_value, optional_text
        enum_value(self.role, Role, "message role")
        optional_text(self.content)
        optional_text(self.tool_call_id)
        if not isinstance(self.tool_calls, list) or not isinstance(self.continuation, dict):
            raise Error.invalid("Invalid tool calls or continuation metadata")
        self.tool_calls = [ToolCall.from_dict(v) if isinstance(v, dict) else v for v in self.tool_calls]
        for call in self.tool_calls:
            if not isinstance(call, ToolCall):
                raise Error.invalid("Invalid tool call")
            text(call.id, "tool call ID")
            text(call.name, "tool name")
            text(call.arguments, "tool arguments", empty=True)

    @classmethod
    def text(cls, role, content):
        return cls(role, text(content, "message content", empty=True))

    @classmethod
    def tool(cls, call_id, result):
        from ariadne._util import dumps
        return cls(Role.TOOL, dumps(result), tool_call_id=call_id)


@dataclass
class ToolDefinition(JsonModel):
    name: str
    description: str
    input_schema: dict

    def __post_init__(self):
        text(self.name, "tool name")
        text(self.description, "tool description", empty=True)
        if not isinstance(self.input_schema, dict):
            raise Error.invalid("Tool input schema must be an object")


@dataclass
class Request(JsonModel):
    messages: list[Message] = field(default_factory=list)
    tools: list[ToolDefinition] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.messages, list) or not isinstance(self.tools, list):
            raise Error.invalid("Request messages and tools must be lists")
        self.messages = [Message.from_dict(v) if isinstance(v, dict) else v for v in self.messages]
        self.tools = [ToolDefinition.from_dict(v) if isinstance(v, dict) else v for v in self.tools]
        if any(not isinstance(v, Message) for v in self.messages) or any(not isinstance(v, ToolDefinition) for v in self.tools):
            raise Error.invalid("Invalid model message/tool types")


@dataclass
class Usage(JsonModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None


@dataclass
class Response(JsonModel):
    message: Message
    finish_reason: str
    usage: Usage = field(default_factory=Usage)
    provider_request_id: str | None = None
    model: str | None = None

    def __post_init__(self):
        if isinstance(self.message, dict):
            self.message = Message.from_dict(self.message)
        if isinstance(self.usage, dict):
            self.usage = Usage.from_dict(self.usage)
