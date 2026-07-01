"""Compatibility imports for the former UI agent adapter module."""

from src.ariadne.application.agent_runner import handle_message
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
