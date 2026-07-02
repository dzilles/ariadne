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


def conversation_to_text(messages: list[Any]) -> str:
    """Convert UI messages into a plain-text transcript for copying/debugging."""
    lines: list[str] = []
    for message in messages:
        text = message_to_text(message)
        if text:
            if lines:
                lines.append("")
            lines.append(text)
    return "\n".join(lines)


def message_to_text(message: Any) -> str:
    """Convert one UI message into plain text."""
    if isinstance(message, UserMessage):
        return f"User:\n{message.content}"
    if isinstance(message, BotResponse):
        return bot_response_to_text(message)
    return ""


def bot_response_to_text(response: BotResponse) -> str:
    """Convert a bot response, including tool/debug rows, into plain text."""
    lines = ["Assistant:"]
    if response.status:
        lines.append(_status_line_to_text("Active", response.status))
    for status in response.tool_results:
        lines.append(_status_line_to_text("Event", status))
    if response.response:
        lines.append(response.response)
    if response.state.name == "CANCELLED":
        lines.append("Cancelled.")
    if response.token_usage:
        usage = response.token_usage
        parts = []
        if "input_tokens" in usage:
            parts.append(f"in {usage['input_tokens']}")
        if "output_tokens" in usage:
            parts.append(f"out {usage['output_tokens']}")
        if "total_tokens" in usage:
            parts.append(f"total {usage['total_tokens']}")
        if parts:
            lines.append("Tokens: " + " | ".join(parts))
    return "\n".join(lines) if len(lines) > 1 else ""


def last_bot_response_text(messages: list[Any]) -> str:
    """Return copyable text for the most recent bot response with content."""
    for message in reversed(messages):
        if isinstance(message, BotResponse):
            text = bot_response_to_text(message)
            if text:
                return text
    return ""


def _status_line_to_text(prefix: str, status: Any) -> str:
    if not status.detail:
        return f"{prefix}: {status.label}"
    detail = str(status.detail)
    if "\n" not in detail:
        return f"{prefix}: {status.label}: {detail}"
    indented = "\n".join(f"  {line}" for line in detail.splitlines())
    return f"{prefix}: {status.label}\n{indented}"
