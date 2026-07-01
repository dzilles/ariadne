"""Typed boundary objects exchanged between the application and UI layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ToolStatus = Literal["start", "success", "error", "cancelled"]


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


@dataclass(frozen=True)
class ToolEvent:
    """Tool execution event suitable for UI rendering."""

    name: str
    status: ToolStatus
    args: dict
    result: str = ""


@dataclass(frozen=True)
class CommandResult:
    """Result of an application command rendered by the UI."""

    message: str
    is_error: bool = False
