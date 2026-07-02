"""Typed boundary objects exchanged between the application and UI layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ToolStatus = Literal["start", "success", "error", "cancelled"]
RunEventType = Literal[
    "run_started",
    "run_finished",
    "thinking",
    "response_start",
    "response_delta",
    "tool_start",
    "token_usage",
    "complete",
    "error",
    "cancelled",
    "queued",
]


@dataclass(frozen=True)
class AgentInfo:
    """Display-safe description of an available agent."""

    name: str
    description: str = ""


@dataclass(frozen=True)
class WorkItemInfo:
    """Display-safe active work item state."""

    id: str
    title: str | None
    status: str | None


@dataclass(frozen=True)
class TokenUsage:
    """Model token usage reported for a run or active work item."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_dict(cls, usage: dict[str, int] | None) -> "TokenUsage | None":
        """Create token usage from provider metadata."""
        if not usage:
            return None
        return cls(
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
        )

    def to_dict(self) -> dict[str, int]:
        """Convert token usage to the UI's dictionary shape."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class ToolEvent:
    """Tool execution event suitable for UI rendering."""

    name: str
    status: ToolStatus
    args: dict
    result: str = ""


@dataclass(frozen=True)
class RunEvent:
    """Agent run event suitable for UI rendering."""

    type: RunEventType
    message: str = ""
    detail: str = ""
    tool_name: str = ""
    run_id: str = ""
    agent_name: str = ""
    args: dict | None = None
    duration_seconds: float | None = None
    usage: TokenUsage | None = None


@dataclass(frozen=True)
class CommandResult:
    """Result of an application command rendered by the UI."""

    message: str
    is_error: bool = False
