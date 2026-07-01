"""Application-facing interfaces for Ariadne."""

from .ui_contract import (
    AgentInfo,
    CommandResult,
    RunEvent,
    TokenUsage,
    ToolEvent,
    WorkItemInfo,
)
from .commands import APPLICATION_COMMANDS, ApplicationCommandSpec

__all__ = [
    "AriadneApplicationController",
    "AGENT_CLASSES",
    "AGENT_DESCRIPTIONS",
    "APPLICATION_COMMANDS",
    "AgentInfo",
    "ApplicationCommandSpec",
    "CommandResult",
    "RunEvent",
    "TokenUsage",
    "ToolEvent",
    "WorkItemInfo",
    "get_agent_names",
]


def __getattr__(name: str):
    """Lazily expose heavy application objects."""
    if name == "AriadneApplicationController":
        from .controller import AriadneApplicationController

        return AriadneApplicationController
    if name in {"AGENT_CLASSES", "AGENT_DESCRIPTIONS", "get_agent_names"}:
        from . import agents

        return getattr(agents, name)
    raise AttributeError(name)
