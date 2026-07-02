"""Import and export chat conversation archives."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .message import BotResponse, UserMessage


def conversation_to_records(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert UI messages into JSON-serializable records."""
    records: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserMessage):
            records.append({"role": "user", "content": message.content})
        elif isinstance(message, BotResponse):
            entry: dict[str, Any] = {"role": "assistant"}
            if message.response:
                entry["response"] = message.response
            if message.token_usage:
                entry["token_usage"] = message.token_usage
            if message.errors:
                entry["errors"] = [
                    {"label": error.label, "detail": error.detail}
                    for error in message.errors
                ]
            records.append(entry)
    return records


def write_conversation_archive(messages: list[Any], filename: str) -> None:
    """Write a conversation archive to disk."""
    Path(filename).write_text(
        json.dumps(conversation_to_records(messages), indent=2),
        encoding="utf-8",
    )


def read_conversation_archive(filename: str) -> list[dict[str, Any]]:
    """Read a conversation archive from disk."""
    return json.loads(Path(filename).read_text(encoding="utf-8"))
