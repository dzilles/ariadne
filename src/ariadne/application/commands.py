"""Application-specific command metadata."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationCommandSpec:
    name: str
    description: str
    args: str = ""


APPLICATION_COMMANDS = [
    ApplicationCommandSpec("save", "Save chat history for current agent"),
    ApplicationCommandSpec("load", "Load chat history for current agent"),
    ApplicationCommandSpec("history", "Show history status for all agents"),
    ApplicationCommandSpec("clearhistory", "Clear saved history for current agent"),
    ApplicationCommandSpec("secret", "Manage API keys in secure vault", "[key] [value]"),
    ApplicationCommandSpec("copy", "Copy last response to clipboard"),
]
