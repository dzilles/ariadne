"""Ariadne TUI - A minimalist terminal chat UI."""

from .app import ChatUI, Agent
from .message import (
    BotResponse,
    Conversation,
    ResponseState,
    StatusLine,
    UserMessage,
)
from .commands import Command, CommandRegistry, create_default_commands

__version__ = "0.1.0"

__all__ = [
    # Main application
    "ChatUI",
    "Agent",
    # Message types
    "BotResponse",
    "Conversation",
    "ResponseState",
    "StatusLine",
    "UserMessage",
    # Commands
    "Command",
    "CommandRegistry",
    "create_default_commands",
]
