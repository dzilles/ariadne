"""Message data structures for the chat UI."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable


class ResponseState(Enum):
    """State of a bot response."""
    IDLE = auto()
    THINKING = auto()
    SUCCESS = auto()
    INFO = auto()
    ERROR = auto()
    CANCELLED = auto()


@dataclass
class StatusLine:
    """A status line with label and detail."""
    label: str
    detail: str
    is_error: bool = False
    is_success: bool = False


@dataclass
class UserMessage:
    """A message from the user."""
    content: str


@dataclass
class BotResponse:
    """A response from the bot.

    Has a dynamic status line that gets replaced, persistent errors,
    and a final response.
    """
    # Dynamic status (gets replaced with each update)
    status: StatusLine | None = None

    # Persistent errors (failed operations stay visible)
    errors: list[StatusLine] = field(default_factory=list)

    # Persistent successes (successful operations, shown in verbose mode)
    successes: list[StatusLine] = field(default_factory=list)

    # All tool results in chronological order (for ordered display)
    tool_results: list[StatusLine] = field(default_factory=list)

    # Final response content
    response: str | None = None

    # Token usage reported by the model provider for this run
    token_usage: dict[str, int] | None = None

    # Current state
    state: ResponseState = ResponseState.IDLE

    # Cancellation flag
    _cancelled: bool = False

    _on_update: Callable[[], None] | None = None

    def set_update_callback(self, callback: Callable[[], None]) -> None:
        """Set callback to be called when response updates."""
        self._on_update = callback

    def _notify_update(self) -> None:
        """Notify that the response has been updated."""
        if self._on_update:
            self._on_update()

    @property
    def is_cancelled(self) -> bool:
        """Check if the response has been cancelled."""
        return self._cancelled

    def cancel(self) -> "BotResponse":
        """Cancel this response."""
        self._cancelled = True
        self.status = None
        self.state = ResponseState.CANCELLED
        self._notify_update()
        return self

    def set_status(self, label: str, detail: str = "") -> "BotResponse":
        """Set the dynamic status line (replaces previous status).

        Args:
            label: Status label (e.g., "Thinking", "Tool")
            detail: Status detail (e.g., "Analyzing request...")
        """
        self.status = StatusLine(label=label, detail=detail)
        self.state = ResponseState.THINKING
        self._notify_update()
        return self

    def update_status(self, detail: str) -> "BotResponse":
        """Update the detail of the current status."""
        if self.status:
            self.status.detail = detail
            self._notify_update()
        return self

    def add_error(self, label: str, detail: str = "") -> "BotResponse":
        """Add a persistent error (stays visible).

        Args:
            label: Error label (e.g., "Tool Failed")
            detail: Error detail (e.g., "Permission denied")
        """
        status = StatusLine(label=label, detail=detail, is_error=True)
        self.errors.append(status)
        self.tool_results.append(status)
        self._notify_update()
        return self

    def complete(self, content: str | None = None) -> "BotResponse":
        """Complete the response successfully.

        Args:
            content: The final response content. If None, just marks complete.
        """
        self.status = None  # Clear dynamic status
        if content is not None:
            self.response = content
        self.state = ResponseState.SUCCESS
        self._notify_update()
        return self

    def set_token_usage(self, usage: dict[str, int] | None) -> "BotResponse":
        """Set model token usage for this response."""
        self.token_usage = usage
        self._notify_update()
        return self

    def error(self, content: str) -> "BotResponse":
        """Complete the response with an error.

        Args:
            content: Error message
        """
        self.add_error("Error", content)
        self.status = None  # Clear dynamic status
        self.state = ResponseState.ERROR
        self._notify_update()
        return self

    def info(self, content: str) -> "BotResponse":
        """Complete the response with an info message (system/settings messages).

        Args:
            content: Info message content
        """
        self.status = None  # Clear dynamic status
        self.response = content
        self.state = ResponseState.INFO
        self._notify_update()
        return self

    # Convenience methods
    def thinking(self, detail: str = "") -> "BotResponse":
        """Set status to thinking."""
        return self.set_status("Thinking", detail)

    def tool(self, name: str, detail: str = "") -> "BotResponse":
        """Set status to a tool call."""
        return self.set_status(f"Tool: {name}", detail)

    def tool_error(self, name: str, detail: str = "") -> "BotResponse":
        """Add a persistent tool error."""
        return self.add_error(f"Tool Failed: {name}", detail)

    def add_success(self, label: str, detail: str = "") -> "BotResponse":
        """Add a persistent success (shown in verbose mode).

        Args:
            label: Success label (e.g., "Tool Completed")
            detail: Success detail (e.g., "Retrieved 5 items")
        """
        status = StatusLine(label=label, detail=detail, is_success=True)
        self.successes.append(status)
        self.tool_results.append(status)
        self._notify_update()
        return self

    def tool_success(self, name: str, detail: str = "") -> "BotResponse":
        """Add a persistent tool success (shown in verbose mode)."""
        return self.add_success(f"Tool: {name}", detail)

    # Streaming support
    def start_response(self) -> "BotResponse":
        """Start streaming a response."""
        self.status = None
        self.response = ""
        self.state = ResponseState.THINKING
        self._notify_update()
        return self

    def append_response(self, content: str) -> "BotResponse":
        """Append to the streaming response."""
        if self.response is None:
            self.response = ""
        self.response += content
        self._notify_update()
        return self

    def has_content(self) -> bool:
        """Check if there's any content to display."""
        return bool(self.status or self.tool_results or self.response)


@dataclass
class Conversation:
    """A conversation between user and bot."""
    messages: list[UserMessage | BotResponse] = field(default_factory=list)
    system_message: str | None = None
    _on_update: Callable[[], None] | None = None

    def set_update_callback(self, callback: Callable[[], None]) -> None:
        """Set callback to be called when conversation updates."""
        self._on_update = callback

    def _notify_update(self) -> None:
        """Notify that the conversation has been updated."""
        if self._on_update:
            self._on_update()

    def set_system_message(self, content: str) -> None:
        """Set the system message."""
        self.system_message = content

    def add_user_message(self, content: str) -> UserMessage:
        """Add a user message."""
        msg = UserMessage(content=content)
        self.messages.append(msg)
        self._notify_update()
        return msg

    def add_bot_response(self) -> BotResponse:
        """Add a new bot response."""
        response = BotResponse()
        response.set_update_callback(self._notify_update)
        self.messages.append(response)
        self._notify_update()
        return response

    def clear(self) -> None:
        """Clear all messages."""
        self.messages.clear()
        self._notify_update()

    def to_openai_messages(self) -> list[dict]:
        """Convert conversation to OpenAI API format."""
        messages = []
        if self.system_message:
            messages.append({"role": "system", "content": self.system_message})

        for msg in self.messages:
            if isinstance(msg, UserMessage):
                messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, BotResponse):
                if msg.response:
                    messages.append({
                        "role": "assistant",
                        "content": msg.response,
                    })
        return messages

    def to_anthropic_messages(self) -> tuple[str | None, list[dict]]:
        """Convert conversation to Anthropic API format."""
        messages = []
        for msg in self.messages:
            if isinstance(msg, UserMessage):
                messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, BotResponse):
                if msg.response:
                    messages.append({
                        "role": "assistant",
                        "content": msg.response,
                    })
        return self.system_message, messages
