"""Command handling for the chat UI."""

from dataclasses import dataclass
from typing import Callable, Awaitable


# Type for completions: either a static list or a callable
# Callable can take optional context (current args) for context-aware completions
CompletionsProvider = Callable[[], list[str]] | Callable[[str], list[str]] | list[str] | None


@dataclass
class Command:
    """A slash command."""
    name: str
    description: str
    args: str = ""
    handler: Callable[..., Awaitable[None]] | None = None
    completions: CompletionsProvider = None

    @property
    def usage(self) -> str:
        """Get the command usage string."""
        if self.args:
            return f"/{self.name} {self.args}"
        return f"/{self.name}"

    def matches(self, query: str) -> bool:
        """Check if command matches a query (without leading /)."""
        return self.name.startswith(query.lower())

    def get_completions(self, query: str = "") -> list[str]:
        """Get available completions for this command's arguments.

        The query is the full argument string (everything after the command).
        For context-aware completions, the provider can accept this string.
        """
        if self.completions is None:
            return []

        if callable(self.completions):
            # Try calling with context first, fall back to no-args
            import inspect
            sig = inspect.signature(self.completions)
            if len(sig.parameters) >= 1:
                items = self.completions(query)
            else:
                items = self.completions()
        else:
            items = self.completions

        # Filter by the last "word" being typed
        if " " in query:
            # Multi-word: filter by the part after the last space
            filter_query = query.split()[-1] if query.split() else ""
        else:
            filter_query = query

        if not filter_query:
            return items

        filter_lower = filter_query.lower()
        return [item for item in items if item.lower().startswith(filter_lower)]


class CommandRegistry:
    """Registry of available commands."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(
        self,
        name: str,
        description: str,
        args: str = "",
    ) -> Callable[[Callable[..., Awaitable[None]]], Callable[..., Awaitable[None]]]:
        """Decorator to register a command handler."""
        def decorator(func: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
            self._commands[name] = Command(
                name=name,
                description=description,
                args=args,
                handler=func,
            )
            return func
        return decorator

    def add(self, name: str, description: str, args: str = "") -> None:
        """Add a command without a handler (for built-in commands)."""
        self._commands[name] = Command(name=name, description=description, args=args)

    def set_handler(self, name: str, handler: Callable[..., Awaitable[None]]) -> None:
        """Set the handler for an existing command."""
        if name in self._commands:
            self._commands[name].handler = handler

    def set_completions(self, name: str, completions: CompletionsProvider) -> None:
        """Set the completions provider for an existing command."""
        if name in self._commands:
            self._commands[name].completions = completions

    def get(self, name: str) -> Command | None:
        """Get a command by name."""
        return self._commands.get(name)

    def search(self, query: str) -> list[Command]:
        """Search for commands matching a query."""
        if not query:
            return list(self._commands.values())
        return [cmd for cmd in self._commands.values() if cmd.matches(query)]

    def all(self) -> list[Command]:
        """Get all registered commands."""
        return list(self._commands.values())


def create_default_commands() -> CommandRegistry:
    """Create the default command registry."""
    registry = CommandRegistry()
    registry.add("clear", "Clear conversation")
    registry.add("export", "Save conversation to file", "[filename]")
    registry.add("help", "Show available commands")
    registry.add("import", "Load conversation from file", "[filename]")
    registry.add("quit", "Exit application")
    return registry
