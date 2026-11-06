from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ariadne._util import JsonModel, to_data
from ariadne.llm import Message, Usage


class State(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass
class Entry(JsonModel):
    id: str
    message: Message
    call_id: str | None = None
    usage: Usage | None = None

    def __post_init__(self):
        if isinstance(self.message, dict):
            self.message = Message.from_dict(self.message)
        if isinstance(self.usage, dict):
            self.usage = Usage.from_dict(self.usage)


@dataclass
class Conversation(JsonModel):
    id: str
    project_id: str
    profile_id: str
    snapshot_id: str
    model: str
    provider_id: str
    title: str
    version: int
    updated_at: str
    state: str = "idle"
    active_run_id: str | None = None
    last_error: dict | None = None
    entries: list[Entry] = field(default_factory=list)

    def __post_init__(self):
        self.entries = [Entry.from_dict(v) if isinstance(v, dict) else v for v in self.entries]

    def view(self):
        """Public conversation data for a future frontend, without internal prompts."""
        result = {key: to_data(getattr(self, key)) for key in self.__dataclass_fields__ if key != "entries"}
        result["messages"] = [{"id": e.id, "role": e.message.role, "content": e.message.content,
                               "tool_calls": [{"id": c.id, "name": c.name} for c in e.message.tool_calls]}
                              for e in self.entries if e.message.role != "system"]
        return result
