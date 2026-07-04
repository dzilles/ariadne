"""Application-specific command metadata."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationCommandSpec:
    name: str
    description: str
    args: str = ""


APPLICATION_COMMANDS = [
    ApplicationCommandSpec("save", "Save prompt and chat context for all agents"),
    ApplicationCommandSpec("load", "Load prompt and chat context for all agents"),
    ApplicationCommandSpec("history", "Show context status for all agents"),
    ApplicationCommandSpec("clearhistory", "Clear saved context for current agent"),
    ApplicationCommandSpec("secret", "Manage API keys in secure vault", "[key] [value]"),
    ApplicationCommandSpec("copy", "Copy content to clipboard", "[last|all]"),
]
