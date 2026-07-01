"""Custom widgets for the chat UI."""

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, ScrollableContainer
from textual.widgets import Static, TextArea
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


class ActiveWorkItemHeader(Static):
    """Top bar showing the active work item."""

    DEFAULT_CSS = """
    ActiveWorkItemHeader {
        width: 100%;
        height: 1;
        padding: 0 2;
        background: $surface;
        color: $text-muted;
        text-overflow: ellipsis;
    }
    """

    def __init__(
        self,
        work_item_id: str | None = None,
        title: str | None = None,
        status: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.work_item_id = work_item_id
        self.title = title
        self.status = status
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def set_work_item(
        self,
        work_item_id: str | None,
        title: str | None,
        status: str | None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Update the displayed work item."""
        self.work_item_id = work_item_id
        self.title = title
        self.status = status
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.update(self.render())

    def render(self) -> Text:
        """Render active work item details."""
        text = Text()
        text.append("Active work item: ", style="bold")
        if not self.work_item_id:
            text.append("None", style="dim")
            return text

        text.append(f"#{self.work_item_id}", style="bold cyan")
        if self.title:
            text.append("  ")
            text.append(self.title, style="white")
        if self.status:
            text.append("  ")
            text.append(self.status, style="bold green")
        text.append("  ")
        text.append(f"Input tokens: {self.input_tokens}", style="dim")
        text.append("  ")
        text.append(f"Output tokens: {self.output_tokens}", style="dim")
        return text


class LinedContent:
    """A Rich renderable that shows content with a continuous vertical line.

    First line shows: ├● content (or └● if is_last)
    Wrapped/continuation lines show: │  content (or spaces if is_last)
    """

    def __init__(
        self,
        label: str,
        detail: str = "",
        dot_style: str = "",
        line_style: str = "dim",
        is_last: bool = False,
    ):
        self.label = label
        self.detail = detail
        self.dot_style = dot_style
        self.line_style = line_style
        self.is_last = is_last

    def __rich_console__(self, console, options):
        """Render with line prefixes on each line."""
        from rich.text import Text

        # Calculate available width for content (minus prefix "├● ")
        prefix_width = 3
        content_width = options.max_width - prefix_width
        if content_width < 10:
            content_width = 10

        # Build the content
        content = Text(self.label)
        if self.detail:
            content.append("\n")
            content.append(self.detail, style="dim")

        # Wrap the content to fit
        lines = content.wrap(console, content_width, justify="left")

        # Build output with line prefixes
        first_line = True
        for line in lines:
            prefix = Text()
            if first_line:
                # Use └ for last item, ├ otherwise
                branch_char = "└" if self.is_last else "├"
                prefix.append(branch_char, style=self.line_style)
                prefix.append("●", style=self.dot_style or self.line_style)
                prefix.append(" ")
                first_line = False
            else:
                # Continue line with │, or space if this is the last item
                if self.is_last:
                    prefix.append("   ")  # Just spaces for last item continuation
                else:
                    prefix.append("│", style=self.line_style)
                    prefix.append("  ")  # Align with content after dot

            yield prefix + line

        # Add continuation line for spacing (unless this is the last item)
        if not self.is_last:
            continuation = Text()
            continuation.append("│", style=self.line_style)
            yield continuation


class StatusWidget(Static):
    """Widget for displaying a status line (label + detail)."""

    DEFAULT_CSS = """
    StatusWidget {
        width: 100%;
        height: auto;
        padding: 0;
    }
    """

    def __init__(
        self,
        status: StatusLine,
        is_error: bool = False,
        is_success: bool = False,
        is_thinking: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.status = status
        self.is_error = is_error
        self.is_success = is_success
        self.is_thinking = is_thinking

    def render(self) -> LinedContent | Text:
        """Render the status widget with continuous vertical line."""
        if self.is_thinking:
            # For thinking, just return simple text (animation handled separately)
            return Text("├● ", style="") + Text(self.status.label)

        # Determine style based on type
        if self.is_error:
            dot_style = "red"
            line_style = "red"
        elif self.is_success:
            dot_style = "green"
            line_style = "green"
        else:
            dot_style = "dim"
            line_style = "dim"

        return LinedContent(
            label=self.status.label,
            detail=self.status.detail,
            dot_style=dot_style,
            line_style=line_style,
        )


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
        padding: 0;
    }


    BotResponseWidget > .response-row > .content {
        width: 1fr;
        height: auto;
    }
    """

    def __init__(self, response: BotResponse, verbose: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.response = response
        self.verbose = verbose

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

        # Show tool results in chronological order
        for result in self.response.tool_results:
            # In non-verbose mode, only show errors
            if result.is_success and not self.verbose:
                continue
            yield StatusWidget(result, is_error=result.is_error, is_success=result.is_success)

        # Show dynamic status (if any)
        if self.response.status:
            yield StatusWidget(self.response.status, is_thinking=True)

        # Show final response (if any)
        if self.response.response:
            with Container(classes="response-row"):
                # Use Rich Text styling for consistent colors with tool indicators
                if self.response.state == ResponseState.SUCCESS:
                    indicator = Text()
                    indicator.append("└", style="green")
                    indicator.append("●", style="green")
                    indicator.append(" ")
                    yield Static(indicator, classes="indicator")
                elif self.response.state == ResponseState.INFO:
                    indicator = Text()
                    indicator.append("└", style="blue")
                    indicator.append("●", style="blue")
                    indicator.append(" ")
                    yield Static(indicator, classes="indicator")
                else:
                    yield Static("└  ", classes="indicator")
                yield Static(Markdown(self.response.response), classes="content")

        if self.response.token_usage:
            usage = self.response.token_usage
            parts = []
            if "input_tokens" in usage:
                parts.append(f"in {usage['input_tokens']}")
            if "output_tokens" in usage:
                parts.append(f"out {usage['output_tokens']}")
            if "total_tokens" in usage:
                parts.append(f"total {usage['total_tokens']}")
            if parts:
                with Container(classes="response-row"):
                    yield Static("   ", classes="indicator")
                    yield Static(Text("Tokens: " + " | ".join(parts), style="dim"), classes="content")


class UserMessageWidget(Static):
    """Widget for displaying a user message."""

    DEFAULT_CSS = """
    UserMessageWidget {
        width: 100%;
        height: auto;
        padding: 0;
    }
    """

    def __init__(self, message: UserMessage, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        """Compose the user message."""
        yield Static(Text(self.message.content))
        yield Separator(connected=True)


class ConversationView(ScrollableContainer):
    """Scrollable view of the conversation."""

    DEFAULT_CSS = """
    ConversationView {
        width: 100%;
        height: 1fr;
        padding: 1 2;
    }
    """

    def __init__(self, conversation: Conversation, settings: Any = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.conversation = conversation
        self._settings = settings

    @property
    def verbose(self) -> bool:
        """Check if verbose mode is enabled."""
        return getattr(self._settings, "verbose", False) if self._settings else False

    def compose(self) -> ComposeResult:
        """Compose the conversation view."""
        for msg in self.conversation.messages:
            if isinstance(msg, UserMessage):
                yield UserMessageWidget(msg)
            elif isinstance(msg, BotResponse):
                yield BotResponseWidget(msg, verbose=self.verbose)

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

    DEFAULT_CSS = """
    Separator {
        width: 100%;
        height: 1;
        color: $text-muted;
        overflow: hidden;
    }
    """

    def __init__(self, connected: bool = False, **kwargs) -> None:
        # Use ┌ at start if connected, for a clean corner into the vertical line
        if connected:
            line = "┌" + "─" * 500
        else:
            line = "─" * 500
        super().__init__(line, **kwargs)


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


class ApprovalDialog(Container):
    """Simple dialog for tool call approval.
    Implementation of ARCH-15. Fulfills REQ-15.
    """

    BINDINGS = [
        Binding("y", "approve_yes", "Yes", show=False),
        Binding("n", "approve_no", "No", show=False),
        Binding("a", "approve_session", "Allow Session", show=False),
        Binding("escape", "approve_no", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    ApprovalDialog {
        width: 100%;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
        display: none;
    }

    ApprovalDialog.visible {
        display: block;
    }

    ApprovalDialog .title {
        text-style: bold;
        color: $warning;
    }

    ApprovalDialog .tool-name {
        color: $primary;
        text-style: bold;
    }

    ApprovalDialog .args {
        color: $text-muted;
    }

    ApprovalDialog .hint {
        margin-top: 1;
    }
    """

    class Response(TextualMessage):
        """Message sent when user responds to approval."""
        def __init__(self, result: str) -> None:
            super().__init__()
            self.result = result  # "yes", "no", or "session"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.tool_name = ""
        self.tool_args: dict = {}
        self.can_focus = True

    def show(self, tool_name: str, args: dict) -> None:
        """Show the approval dialog."""
        self.tool_name = tool_name
        self.tool_args = args
        self.add_class("visible")
        self.refresh(recompose=True)
        self.focus()

    def hide(self) -> None:
        """Hide the approval dialog."""
        self.remove_class("visible")

    def compose(self) -> ComposeResult:
        """Compose the dialog."""
        yield Static("Tool Approval Required", classes="title")

        tool_text = Text()
        tool_text.append("Tool: ", style="dim")
        tool_text.append(self.tool_name, style="bold cyan")
        yield Static(tool_text, classes="tool-name")

        # Format args nicely
        if self.tool_args:
            args_text = Text()
            for key, value in self.tool_args.items():
                value_str = str(value)
                if len(value_str) > 50:
                    value_str = value_str[:50] + "..."
                args_text.append(f"  {key}: ", style="dim")
                args_text.append(f"{value_str}\n")
            yield Static(args_text, classes="args")

        # Key hints
        hint = Text()
        hint.append("[", style="dim")
        hint.append("y", style="bold green")
        hint.append("]es  ", style="dim")
        hint.append("[", style="dim")
        hint.append("n", style="bold red")
        hint.append("]o  ", style="dim")
        hint.append("[", style="dim")
        hint.append("a", style="bold yellow")
        hint.append("]llow session", style="dim")
        yield Static(hint, classes="hint")

    def action_approve_yes(self) -> None:
        """Approve this tool call."""
        if self.has_class("visible"):
            self.hide()
            self.post_message(self.Response("yes"))

    def action_approve_no(self) -> None:
        """Reject this tool call."""
        if self.has_class("visible"):
            self.hide()
            self.post_message(self.Response("no"))

    def action_approve_session(self) -> None:
        """Approve all tool calls for this session."""
        if self.has_class("visible"):
            self.hide()
            self.post_message(self.Response("session"))
