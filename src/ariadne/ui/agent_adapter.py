"""Compatibility imports for the former UI agent adapter module."""

from src.ariadne.application.agents import (
    AGENT_CLASSES,
    AGENT_DESCRIPTIONS,
    get_agent_names,
)

__all__ = [
    "AGENT_CLASSES",
    "AGENT_DESCRIPTIONS",
    "get_agent_names",
    "handle_message",
]


def __getattr__(name: str):
    """Lazily expose the legacy message handler."""
    if name == "handle_message":
        from src.ariadne.application.agent_runner import handle_message

        return handle_message
    raise AttributeError(name)
