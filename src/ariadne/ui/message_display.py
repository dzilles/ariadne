"""Configurable display policies for chat UI events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DisplayMode(str, Enum):
    """How long an event should remain visible."""

    HIDDEN = "hidden"
    TRANSIENT = "transient"
    PERSISTENT = "persistent"
    VERBOSE = "verbose"


class ActivityAnimation(str, Enum):
    """Animation style for active transient messages."""

    NONE = "none"
    WAVE = "wave"


@dataclass(frozen=True)
class DisplayRule:
    """Rendering policy for a status or activity message."""

    mode: DisplayMode
    animation: ActivityAnimation = ActivityAnimation.NONE


RUN_EVENT_RULES = {
    "run_started": DisplayRule(DisplayMode.HIDDEN),
    "run_finished": DisplayRule(DisplayMode.HIDDEN),
    "thinking": DisplayRule(DisplayMode.TRANSIENT, ActivityAnimation.WAVE),
    "response_start": DisplayRule(DisplayMode.HIDDEN),
    "response_delta": DisplayRule(DisplayMode.HIDDEN),
    "tool_start": DisplayRule(DisplayMode.PERSISTENT, ActivityAnimation.WAVE),
    "token_usage": DisplayRule(DisplayMode.HIDDEN),
    "complete": DisplayRule(DisplayMode.HIDDEN),
    "error": DisplayRule(DisplayMode.PERSISTENT),
    "cancelled": DisplayRule(DisplayMode.PERSISTENT),
    "queued": DisplayRule(DisplayMode.PERSISTENT),
}

TOOL_EVENT_RULES = {
    "start": DisplayRule(DisplayMode.PERSISTENT, ActivityAnimation.WAVE),
    "success": DisplayRule(DisplayMode.PERSISTENT),
    "error": DisplayRule(DisplayMode.PERSISTENT),
    "cancelled": DisplayRule(DisplayMode.PERSISTENT),
}


def run_event_rule(event_type: str) -> DisplayRule:
    """Return the configured display rule for a run event."""
    return RUN_EVENT_RULES.get(event_type, DisplayRule(DisplayMode.PERSISTENT))


def tool_event_rule(status: str) -> DisplayRule:
    """Return the configured display rule for a tool event."""
    return TOOL_EVENT_RULES.get(status, DisplayRule(DisplayMode.PERSISTENT))


def wave_style(phase: int) -> str:
    """Return the active-message style for a wave animation frame."""
    styles = ["bold cyan", "cyan", "bright_cyan", "white", "bright_cyan", "cyan"]
    return styles[phase % len(styles)]


def format_tool_call_detail(tool_name: str, args: dict | None) -> str:
    """Return a compact, useful summary of a tool call's visible parameters."""
    args = args or {}
    formatter = TOOL_DETAIL_FORMATTERS.get(tool_name)
    if formatter:
        detail = formatter(args)
    else:
        detail = _format_generic_args(args)
    return detail or "Running..."


def format_tool_result_preview(result: str, max_chars: int = 800) -> str:
    """Return the tool output text shown to the LLM as a compact preview."""
    if not result:
        return "Output: <empty>"
    text = str(result).strip()
    if max_chars >= 0 and len(text) > max_chars:
        text = text[: max(0, max_chars - 1)] + "..."
    return f"Output:\n{text}"


def _format_read_file(args: dict) -> str:
    return _field(args, "file_path", "path", index=0)


def _format_write_file(args: dict) -> str:
    path = _field(args, "file_path", "path", index=0)
    content = _field(args, "content", index=1)
    if path and content:
        return f"{path} ({len(str(content))} chars)"
    return path


def _format_list_files(args: dict) -> str:
    return _field(args, "directory", index=0) or "."


def _format_search_files(args: dict) -> str:
    directory = _field(args, "directory", index=0) or "."
    pattern = _field(args, "pattern", index=1)
    if pattern:
        return f"{directory} | pattern: {pattern}"
    return directory


def _format_shell_command(args: dict) -> str:
    return _truncate(_field(args, "command", index=0), 120)


def _format_files(args: dict) -> str:
    files = _field(args, "files", index=0)
    if isinstance(files, list):
        return ", ".join(str(item) for item in files[:5]) + (
            f" (+{len(files) - 5} more)" if len(files) > 5 else ""
        )
    return str(files) if files else ""


def _format_work_item(args: dict) -> str:
    work_item_id = _field(args, "work_item_id", "ticket_id", index=0)
    return f"#{work_item_id}" if work_item_id else ""


def _format_status(args: dict) -> str:
    work_item = _format_work_item(args)
    status = _field(args, "status", index=1)
    if work_item and status:
        return f"{work_item} -> {status}"
    return work_item or str(status or "")


def _format_comment(args: dict) -> str:
    work_item = _format_work_item(args)
    comment = _truncate(_field(args, "comment", index=1), 80)
    if work_item and comment:
        return f"{work_item}: {comment}"
    return work_item or comment


def _format_gate(args: dict) -> str:
    work_item = _format_work_item(args)
    gate = _field(args, "gate", index=1)
    if work_item and gate:
        return f"{work_item} | {gate}"
    return work_item or str(gate or "")


def _format_link(args: dict) -> str:
    work_item = _format_work_item(args)
    title = _field(args, "title", index=1)
    url = _truncate(_field(args, "url", index=2), 80)
    parts = [part for part in (work_item, str(title or ""), url) if part]
    return " | ".join(parts)


def _format_commit(args: dict) -> str:
    work_item = _format_work_item(args)
    commit_hash = _field(args, "commit_hash", index=1)
    if work_item and commit_hash:
        return f"{work_item} | {commit_hash}"
    return work_item or str(commit_hash or "")


def _format_shared_context(args: dict) -> str:
    work_item = _format_work_item(args)
    author = _field(args, "author", index=1)
    context = _field(args, "context", index=2)
    context_len = len(str(context)) if context else 0
    parts = [part for part in (work_item, str(author or "")) if part]
    if context_len:
        parts.append(f"{context_len} chars")
    return " | ".join(parts)


def _format_git_metadata(args: dict) -> str:
    work_item = _format_work_item(args)
    fields = []
    for key in ("target_branch", "feature_branch", "base_commit", "merge_request_id"):
        value = args.get(key)
        if value:
            fields.append(f"{key}: {value}")
    if work_item:
        fields.insert(0, work_item)
    return " | ".join(fields)


def _format_delegate(args: dict) -> str:
    agent = _field(args, "agent_name", index=0)
    work_item = _format_work_item(args)
    task = _truncate(_field(args, "task_description", index=2), 90)
    parts = [part for part in (str(agent or ""), work_item, task) if part]
    return " | ".join(parts)


def _format_commit_message(args: dict) -> str:
    return _truncate(_field(args, "message", index=0), 100)


def _format_remote(args: dict) -> str:
    return str(_field(args, "remote_name", index=0) or "origin")


def _format_generic_args(args: dict) -> str:
    parts = []
    positional = args.get("args")
    if isinstance(positional, list):
        for item in positional[:3]:
            parts.append(_truncate(item, 60))
    for key, value in args.items():
        if key == "args" or value is None:
            continue
        parts.append(f"{key}: {_truncate(value, 60)}")
    return " | ".join(parts[:4])


def _field(args: dict, *names: str, index: int | None = None) -> Any:
    for name in names:
        if name in args:
            return args[name]
    positional = args.get("args")
    if index is not None and isinstance(positional, list) and len(positional) > index:
        return positional[index]
    return None


def _truncate(value: Any, max_chars: int) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "..."


TOOL_DETAIL_FORMATTERS = {
    "read_file": _format_read_file,
    "write_file": _format_write_file,
    "list_files": _format_list_files,
    "search_files": _format_search_files,
    "run_shell_command": _format_shell_command,
    "get_status": lambda args: "repository status",
    "get_current_branch": lambda args: "current branch",
    "create_branch": lambda args: str(_field(args, "branch_name", index=0) or ""),
    "checkout_branch": lambda args: str(_field(args, "branch_name", index=0) or ""),
    "add_files": _format_files,
    "commit_changes": _format_commit_message,
    "push_changes": _format_remote,
    "get_work_item": _format_work_item,
    "get_work_item_info": _format_work_item,
    "get_ticket": _format_work_item,
    "list_work_items": lambda args: "all work items",
    "activate_work_item": _format_work_item,
    "update_status": _format_status,
    "post_comment": _format_comment,
    "approve_gate": _format_gate,
    "reject_gate": _format_gate,
    "add_link": _format_link,
    "add_commit_hash": _format_commit,
    "append_shared_context": _format_shared_context,
    "update_git_metadata": _format_git_metadata,
    "delegate_to_agent": _format_delegate,
}
