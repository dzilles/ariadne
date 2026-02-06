"""Custom widgets for the chat UI."""

from textual.app import ComposeResult
from textual.containers import Container, Vertical, ScrollableContainer
from textual.widgets import Static, TextArea
from textual.widgets.text_area import TextAreaTheme
from textual.reactive import reactive
from textual.message import Message as TextualMessage
from textual.binding import Binding
from rich.text import Text
from rich.markdown import Markdown

from .message import (
    Conversation,
    UserMessage,
    BotResponse,
    StatusLine,
    ResponseState,
)
from .commands import Command


class ThinkingIndicator(Static):
    """Animated thinking indicator (pulsating dot)."""

    ANIMATION_FRAMES = ["·", "•", "●", "•", "·", " "]
    frame = reactive(0)
    active = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__("●", **kwargs)
        self._timer = None

    def on_mount(self) -> None:
        """Start the animation timer."""
        self._timer = self.set_interval(0.15, self._next_frame)

    def _next_frame(self) -> None:
        """Advance to the next animation frame."""
        if self.active:
            self.frame = (self.frame + 1) % len(self.ANIMATION_FRAMES)

    def watch_frame(self, frame: int) -> None:
        """Update display when frame changes."""
        if self.active:
            self.update(self.ANIMATION_FRAMES[frame])

    def watch_active(self, active: bool) -> None:
        """Update display when active state changes."""
        if not active:
            self.update("●")


class StatusWidget(Static):
    """Widget for displaying a status line (label + detail)."""

    DEFAULT_CSS = """
    StatusWidget {
        width: 100%;
        height: auto;
        padding: 0;
        layout: horizontal;
    }

    StatusWidget > .indicator {
        width: 3;
        min-width: 3;
        max-width: 3;
        height: auto;
        padding: 0 1 0 0;
    }

    StatusWidget > .indicator.error {
        color: $error;
    }

    StatusWidget > .content {
        width: 1fr;
        height: auto;
    }

    StatusWidget > .content > .label {
        color: $text;
    }

    StatusWidget > .content > .detail {
        color: $text-muted;
    }
    """

    def __init__(
        self,
        status: StatusLine,
        is_error: bool = False,
        is_thinking: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.status = status
        self.is_error = is_error
        self.is_thinking = is_thinking

    def compose(self) -> ComposeResult:
        """Compose the status widget."""
        if self.is_thinking:
            indicator = ThinkingIndicator(classes="indicator")
            indicator.active = True
            yield indicator
        elif self.is_error:
            yield Static("●", classes="indicator error")
        else:
            yield Static(" ", classes="indicator")

        with Vertical(classes="content"):
            yield Static(Text(self.status.label), classes="label")
            if self.status.detail:
                yield Static(Text(self.status.detail, style="dim"), classes="detail")


class BotResponseWidget(Static):
    """Widget for displaying a bot response."""

    DEFAULT_CSS = """
    BotResponseWidget {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
    }

    BotResponseWidget.empty {
        display: none;
    }

    BotResponseWidget > .response-row {
        width: 100%;
        height: auto;
        layout: horizontal;
    }

    BotResponseWidget > .response-row > .indicator {
        width: 3;
        min-width: 3;
        max-width: 3;
        height: auto;
        padding: 0 1 0 0;
    }

    BotResponseWidget > .response-row > .indicator.success {
        color: $success;
    }

    BotResponseWidget > .response-row > .content {
        width: 1fr;
        height: auto;
    }
    """

    def __init__(self, response: BotResponse, **kwargs) -> None:
        super().__init__(**kwargs)
        self.response = response

    def on_mount(self) -> None:
        """Update visibility on mount."""
        self._update_visibility()

    def _update_visibility(self) -> None:
        """Show/hide based on whether there's content."""
        if self.response.has_content():
            self.remove_class("empty")
        else:
            self.add_class("empty")

    def compose(self) -> ComposeResult:
        """Compose the bot response."""
        self._update_visibility()
        if not self.response.has_content():
            return

        # Show persistent errors first
        for error in self.response.errors:
            yield StatusWidget(error, is_error=True)

        # Show dynamic status (if any)
        if self.response.status:
            yield StatusWidget(self.response.status, is_thinking=True)

        # Show final response (if any)
        if self.response.response:
            with Container(classes="response-row"):
                if self.response.state == ResponseState.SUCCESS:
                    yield Static("●", classes="indicator success")
                else:
                    yield Static(" ", classes="indicator")
                yield Static(Markdown(self.response.response), classes="content")


class UserMessageWidget(Static):
    """Widget for displaying a user message."""

    DEFAULT_CSS = """
    UserMessageWidget {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
    }
    """

    def __init__(self, message: UserMessage, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        """Compose the user message."""
        yield Separator()
        yield Static(Text(self.message.content))


class ConversationView(ScrollableContainer):
    """Scrollable view of the conversation."""

    DEFAULT_CSS = """
    ConversationView {
        width: 100%;
        height: 1fr;
        padding: 1 2;
    }
    """

    def __init__(self, conversation: Conversation, **kwargs) -> None:
        super().__init__(**kwargs)
        self.conversation = conversation

    def compose(self) -> ComposeResult:
        """Compose the conversation view."""
        for msg in self.conversation.messages:
            if isinstance(msg, UserMessage):
                yield UserMessageWidget(msg)
            elif isinstance(msg, BotResponse):
                yield BotResponseWidget(msg)

    def refresh_conversation(self) -> None:
        """Refresh the conversation display."""
        self.refresh(recompose=True)
        self.call_after_refresh(self.scroll_end)


class CommandSuggestion(Static):
    """A single command suggestion."""

    DEFAULT_CSS = """
    CommandSuggestion {
        width: 100%;
        padding: 0 2 0 7;
    }

    CommandSuggestion.selected {
        background: $surface;
    }
    """

    def __init__(self, command: Command, selected: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.command = command
        if selected:
            self.add_class("selected")

    def compose(self) -> ComposeResult:
        """Compose the command suggestion."""
        text = Text()
        text.append(self.command.usage.ljust(20))
        text.append(self.command.description, style="dim")
        yield Static(text)


class ArgumentSuggestion(Static):
    """A single argument suggestion."""

    DEFAULT_CSS = """
    ArgumentSuggestion {
        width: 100%;
        padding: 0 2 0 7;
    }

    ArgumentSuggestion.selected {
        background: $surface;
    }
    """

    def __init__(self, value: str, selected: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.value = value
        if selected:
            self.add_class("selected")

    def compose(self) -> ComposeResult:
        """Compose the argument suggestion."""
        yield Static(Text(self.value))


class CommandSuggestions(Container):
    """Container for command/argument suggestions dropdown."""

    DEFAULT_CSS = """
    CommandSuggestions {
        width: 100%;
        height: auto;
        max-height: 10;
        padding: 1 0;
        display: none;
    }

    CommandSuggestions.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.commands: list[Command] = []
        self.arguments: list[str] = []
        self.selected_index = 0
        self._mode: str = "commands"  # "commands" or "arguments"

    def show(self, commands: list[Command]) -> None:
        """Show suggestions for the given commands."""
        self.commands = commands
        self.arguments = []
        self._mode = "commands"
        self.selected_index = 0
        self.add_class("visible")
        self.refresh(recompose=True)

    def show_arguments(self, arguments: list[str]) -> None:
        """Show suggestions for command arguments."""
        self.arguments = arguments
        self.commands = []
        self._mode = "arguments"
        self.selected_index = 0
        self.add_class("visible")
        self.refresh(recompose=True)

    def hide(self) -> None:
        """Hide the suggestions."""
        self.remove_class("visible")
        self.commands = []
        self.arguments = []

    @property
    def _items(self) -> list:
        """Get current items based on mode."""
        return self.commands if self._mode == "commands" else self.arguments

    def select_next(self) -> None:
        """Select the next suggestion."""
        items = self._items
        if items:
            self.selected_index = (self.selected_index + 1) % len(items)
            self.refresh(recompose=True)

    def select_previous(self) -> None:
        """Select the previous suggestion."""
        items = self._items
        if items:
            self.selected_index = (self.selected_index - 1) % len(items)
            self.refresh(recompose=True)

    def get_selected(self) -> Command | None:
        """Get the currently selected command."""
        if self._mode == "commands" and self.commands:
            if 0 <= self.selected_index < len(self.commands):
                return self.commands[self.selected_index]
        return None

    def get_selected_argument(self) -> str | None:
        """Get the currently selected argument."""
        if self._mode == "arguments" and self.arguments:
            if 0 <= self.selected_index < len(self.arguments):
                return self.arguments[self.selected_index]
        return None

    def is_argument_mode(self) -> bool:
        """Check if currently showing argument suggestions."""
        return self._mode == "arguments"

    def compose(self) -> ComposeResult:
        """Compose the suggestions list."""
        if self._mode == "commands":
            for i, cmd in enumerate(self.commands):
                yield CommandSuggestion(cmd, selected=(i == self.selected_index))
        else:
            for i, arg in enumerate(self.arguments):
                yield ArgumentSuggestion(arg, selected=(i == self.selected_index))


class Separator(Static):
    """A horizontal separator line that fills the width."""

    # Use a very long line - CSS will clip to container width
    LINE = "─" * 500

    DEFAULT_CSS = """
    Separator {
        width: 100%;
        height: 1;
        color: $text-muted;
        overflow: hidden;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(self.LINE, **kwargs)


class ChatTextArea(TextArea):
    """Custom TextArea where Enter submits and Ctrl+Enter creates new line."""

    class Submit(TextualMessage):
        """Posted when user presses Enter to submit."""
        pass

    async def _on_key(self, event) -> None:
        """Override key handling to swap Enter and Ctrl+Enter behavior."""
        key = event.key

        if key == "enter":
            # Enter submits instead of inserting newline
            event.stop()
            event.prevent_default()
            self.post_message(self.Submit())
            return

        if key == "ctrl+enter":
            # Ctrl+Enter inserts newline
            event.stop()
            event.prevent_default()
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            return

        # Let parent handle everything else
        await super()._on_key(event)


class ChatInput(Container):
    """Multi-line input area with command suggestions and history.

    - Enter: Send message
    - Ctrl+Enter: New line
    - Up/Down: Navigate history (when input is single line)
    """

    DEFAULT_CSS = """
    ChatInput {
        width: 100%;
        height: auto;
        padding: 0 2;
    }

    ChatInput TextArea {
        border: none;
        background: transparent;
        width: 100%;
        height: auto;
        min-height: 3;
        max-height: 10;
    }

    ChatInput TextArea:focus {
        border: none;
    }
    """

    class Submitted(TextualMessage):
        """Message sent when input is submitted."""
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class CommandSelected(TextualMessage):
        """Message sent when a command is selected."""
        def __init__(self, command: Command, args: str = "") -> None:
            super().__init__()
            self.command = command
            self.args = args

    def __init__(self, commands: list[Command], **kwargs) -> None:
        super().__init__(**kwargs)
        self.all_commands = commands
        self._history: list[str] = []
        self._history_index: int = 0
        self._current_input: str = ""  # Store current input when navigating history

    def compose(self) -> ComposeResult:
        """Compose the input area."""
        yield Separator()
        yield ChatTextArea(id="chat-input")
        yield Separator()
        yield CommandSuggestions()

    def on_mount(self) -> None:
        """Set up the text area after mounting."""
        # Focus the text area
        self.text_area.focus()

    @property
    def text_area(self) -> ChatTextArea:
        """Get the text area widget."""
        return self.query_one(ChatTextArea)

    def on_chat_text_area_submit(self, event: ChatTextArea.Submit) -> None:
        """Handle Enter key from text area."""
        self._submit()

    @property
    def suggestions(self) -> CommandSuggestions:
        """Get the suggestions widget."""
        return self.query_one(CommandSuggestions)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Handle text area changes."""
        value = event.text_area.text
        # Only show suggestions for single-line starting with /
        if "\n" not in value and value.startswith("/"):
            query = value[1:]  # Remove leading /
            # Check if there are args (space in the query)
            if " " in query:
                # Check for argument completions
                parts = query.split(maxsplit=1)
                cmd_name = parts[0]
                arg_query = parts[1] if len(parts) > 1 else ""

                # Find the command
                cmd = None
                for c in self.all_commands:
                    if c.name == cmd_name:
                        cmd = c
                        break

                if cmd:
                    completions = cmd.get_completions(arg_query)
                    if completions:
                        self.suggestions.show_arguments(completions)
                    else:
                        self.suggestions.hide()
                else:
                    self.suggestions.hide()
            else:
                matches = [cmd for cmd in self.all_commands if cmd.matches(query)]
                if matches:
                    self.suggestions.show(matches)
                else:
                    self.suggestions.hide()
        else:
            self.suggestions.hide()

    def _submit(self) -> None:
        """Submit the current input."""
        value = self.text_area.text.strip()
        if not value:
            return

        # Add to history
        if not self._history or self._history[-1] != value:
            self._history.append(value)
        self._history_index = len(self._history)
        self._current_input = ""

        if value.startswith("/") and "\n" not in value:
            self._handle_command(value)
        else:
            self.post_message(self.Submitted(value))

        self.text_area.text = ""
        self.suggestions.hide()

    def _handle_command(self, value: str) -> None:
        """Handle a command input."""
        parts = value[1:].split(maxsplit=1)
        cmd_name = parts[0] if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        # Find exact match first
        for cmd in self.all_commands:
            if cmd.name == cmd_name:
                self.post_message(self.CommandSelected(cmd, args))
                return

        # If no exact match, use selected suggestion
        selected = self.suggestions.get_selected()
        if selected:
            self.post_message(self.CommandSelected(selected, args))

    def on_key(self, event) -> None:
        """Handle key events for navigation and history."""
        # Command suggestions take priority
        if self.suggestions.has_class("visible"):
            if event.key == "up":
                self.suggestions.select_previous()
                event.prevent_default()
                return
            elif event.key == "down":
                self.suggestions.select_next()
                event.prevent_default()
                return
            elif event.key == "tab":
                if self.suggestions.is_argument_mode():
                    selected_arg = self.suggestions.get_selected_argument()
                    if selected_arg:
                        # Get the command and existing args from current input
                        value = self.text_area.text
                        parts = value[1:].split(maxsplit=1)
                        cmd_name = parts[0] if parts else ""
                        arg_text = parts[1] if len(parts) > 1 else ""

                        # Check if we're completing a second argument
                        arg_parts = arg_text.split()
                        if len(arg_parts) > 1 or (arg_parts and arg_text.endswith(" ")):
                            # Keep first arg, replace/add second
                            first_arg = arg_parts[0]
                            self.text_area.text = f"/{cmd_name} {first_arg} {selected_arg}"
                        else:
                            # First argument completion
                            self.text_area.text = f"/{cmd_name} {selected_arg}"
                        self.text_area.move_cursor(self.text_area.document.end)
                else:
                    selected = self.suggestions.get_selected()
                    if selected:
                        self.text_area.text = f"/{selected.name} "
                        self.text_area.move_cursor(self.text_area.document.end)
                event.prevent_default()
                return
            elif event.key == "escape":
                self.suggestions.hide()
                event.prevent_default()
                return

        # History navigation only works for single-line input
        text = self.text_area.text
        is_single_line = "\n" not in text

        if event.key == "up" and is_single_line:
            self._history_previous()
            event.prevent_default()
        elif event.key == "down" and is_single_line:
            self._history_next()
            event.prevent_default()

    def _history_previous(self) -> None:
        """Navigate to previous history entry."""
        if not self._history:
            return

        # Save current input when starting to navigate
        if self._history_index == len(self._history):
            self._current_input = self.text_area.text

        if self._history_index > 0:
            self._history_index -= 1
            self.text_area.text = self._history[self._history_index]
            self.text_area.move_cursor(self.text_area.document.end)

    def _history_next(self) -> None:
        """Navigate to next history entry."""
        if not self._history:
            return

        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.text_area.text = self._history[self._history_index]
            self.text_area.move_cursor(self.text_area.document.end)
        elif self._history_index == len(self._history) - 1:
            # Return to current input
            self._history_index = len(self._history)
            self.text_area.text = self._current_input
            self.text_area.move_cursor(self.text_area.document.end)
