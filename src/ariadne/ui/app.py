"""Main ChatUI application."""

import asyncio
import base64
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Awaitable, Any

from textual.app import App, ComposeResult
from textual.binding import Binding

from src.ariadne.application.settings_commands import (
    get_settings_completions,
    handle_settings_command,
    supports_settings_command,
)

from .message import Conversation, BotResponse
from .commands import CommandRegistry, create_default_commands
from .conversation_archive import (
    conversation_to_text,
    read_conversation_archive,
    write_conversation_archive,
)
from .widgets import ActiveWorkItemHeader, ChatInput, ConversationView, ApprovalDialog


# Type alias for message handlers
MessageHandler = Callable[[str, BotResponse], Awaitable[None]]
BusyMessageHandler = Callable[[str, BotResponse], Awaitable[None]]
CancelHandler = Callable[[], bool]


@dataclass
class Agent:
    """Represents an agent that can be selected."""
    name: str
    description: str = ""
    metadata: dict | None = None

    def __str__(self) -> str:
        return self.name


class ChatUI(App):
    """A minimalist terminal chat UI.
    Implementation of ARCH-15. Fulfills REQ-15.
    """

    CSS = """
    Screen {
        background: $background;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("ctrl+shift+c", "copy_conversation", "Copy conversation", show=False),
        Binding("escape", "abort", "Abort", show=False),
    ]

    def __init__(
        self,
        title: str = "Chat",
        commands: CommandRegistry | None = None,
        agents: list[Agent] | None = None,
        settings: Any | None = None,
    ) -> None:
        super().__init__()
        self.title = title
        self.conversation = Conversation()
        self.commands = commands or create_default_commands()
        self._message_handler: MessageHandler | None = None
        self._busy_message_handler: BusyMessageHandler | None = None
        self._cancel_handler: CancelHandler | None = None
        self._current_task: asyncio.Task | None = None
        self._current_response: BotResponse | None = None

        # Agent management
        self._agents: list[Agent] = agents or []
        self._active_agent: Agent | None = self._agents[0] if self._agents else None
        self._on_agent_change: Callable[[Agent | None], None] | None = None

        # Active work item display
        self._active_work_item_id: str | None = None
        self._active_work_item_title: str | None = None
        self._active_work_item_status: str | None = None
        self._active_work_item_input_tokens: int = 0
        self._active_work_item_output_tokens: int = 0

        # Settings management (Pydantic model)
        self._settings = settings
        self._on_settings_change: Callable[[str, Any], None] | None = None

        # Tool approval
        self._pending_approval_event: asyncio.Event | None = None
        self._approval_result: str | None = None

        # Set up conversation update callback
        self.conversation.set_update_callback(self._on_conversation_update)

        # Set up built-in command handlers
        self._setup_builtin_commands()

    @property
    def current_response(self) -> BotResponse | None:
        """Return the bot response currently owned by an active run."""
        return self._current_response

    @property
    def is_run_active(self) -> bool:
        """Return True while a message handler task is active."""
        return bool(self._current_task and not self._current_task.done())

    def _setup_builtin_commands(self) -> None:
        """Set up handlers for built-in commands."""
        self.commands.set_handler("clear", self._cmd_clear)
        self.commands.set_handler("quit", self._cmd_quit)
        self.commands.set_handler("help", self._cmd_help)
        self.commands.set_handler("export", self._cmd_export)
        self.commands.set_handler("import", self._cmd_import)
        self.commands.add("agent", "Select or show active agent", "[name]")
        self.commands.set_handler("agent", self._cmd_agent)
        self.commands.set_completions("agent", self._get_agent_completions)

        # Settings command (only if the settings model exposes fields)
        if supports_settings_command(self._settings):
            self.commands.add("settings", "View or change settings", "[field] [value]")
            self.commands.set_handler("settings", self._cmd_settings)
            self.commands.set_completions("settings", self._get_settings_completions)

    def _get_agent_completions(self) -> list[str]:
        """Get available agent names for completions."""
        return [agent.name for agent in self._agents]

    # -------------------------------------------------------------------------
    # Settings management
    # -------------------------------------------------------------------------

    def get_settings(self) -> Any:
        """Get the current settings model."""
        return self._settings

    def on_settings_change(
        self, callback: Callable[[str, Any], None]
    ) -> Callable[[str, Any], None]:
        """Decorator to register a callback for settings changes."""
        self._on_settings_change = callback
        return callback

    def _get_settings_completions(self, context: str = "") -> list[str]:
        """Get available completions for settings command.

        Context-aware: returns field names first, then field choices.
        """
        return get_settings_completions(self._settings, context)

    async def _cmd_settings(self, args: str = "") -> None:
        """Show or change settings."""
        response = self.conversation.add_bot_response()
        result = handle_settings_command(
            self._settings,
            args,
            on_change=self._on_settings_change,
        )
        if result.is_error:
            response.error(result.message)
        else:
            response.info(result.message)

    # -------------------------------------------------------------------------
    # Agent management
    # -------------------------------------------------------------------------

    def set_agents(self, agents: list[Agent]) -> None:
        """Set the available agents."""
        self._agents = agents
        if agents and not self._active_agent:
            self._active_agent = agents[0]

    def get_agents(self) -> list[Agent]:
        """Get the list of available agents."""
        return self._agents.copy()

    def get_active_agent(self) -> Agent | None:
        """Get the currently active agent."""
        return self._active_agent

    def set_active_agent(self, agent: Agent | str | None) -> None:
        """Set the active agent by name or Agent object."""
        if agent is None:
            self._active_agent = None
        elif isinstance(agent, str):
            for a in self._agents:
                if a.name.lower() == agent.lower():
                    self._active_agent = a
                    break
        else:
            self._active_agent = agent

        if self._on_agent_change:
            self._on_agent_change(self._active_agent)

    def on_agent_change(
        self, callback: Callable[[Agent | None], None]
    ) -> Callable[[Agent | None], None]:
        """Decorator to register a callback for agent changes."""
        self._on_agent_change = callback
        return callback

    def set_active_work_item_info(
        self,
        work_item_id: str | None,
        title: str | None,
        status: str | None,
    ) -> None:
        """Update the active work item shown in the top bar."""
        if work_item_id != self._active_work_item_id:
            self._active_work_item_input_tokens = 0
            self._active_work_item_output_tokens = 0
        self._active_work_item_id = work_item_id
        self._active_work_item_title = title
        self._active_work_item_status = status
        try:
            header = self.query_one(ActiveWorkItemHeader)
            header.set_work_item(
                work_item_id,
                title,
                status,
                self._active_work_item_input_tokens,
                self._active_work_item_output_tokens,
            )
        except Exception:
            pass  # Header may not be mounted yet

    def add_active_work_item_token_usage(self, usage: dict[str, int] | None) -> None:
        """Add token usage to the active work item top bar."""
        if not usage or not self._active_work_item_id:
            return

        self._active_work_item_input_tokens += int(usage.get("input_tokens", 0) or 0)
        self._active_work_item_output_tokens += int(usage.get("output_tokens", 0) or 0)
        try:
            header = self.query_one(ActiveWorkItemHeader)
            header.set_work_item(
                self._active_work_item_id,
                self._active_work_item_title,
                self._active_work_item_status,
                self._active_work_item_input_tokens,
                self._active_work_item_output_tokens,
            )
        except Exception:
            pass  # Header may not be mounted yet

    async def _cmd_clear(self) -> None:
        """Clear the conversation."""
        self.conversation.clear()

    async def _cmd_quit(self) -> None:
        """Quit the application."""
        self.exit()

    async def _cmd_agent(self, name: str = "") -> None:
        """Show or select an agent."""
        response = self.conversation.add_bot_response()

        if not self._agents:
            response.complete("No agents configured.")
            return

        if name and self._current_task and not self._current_task.done():
            response.info(
                "An agent run is active. Press `Escape` to request cancellation, "
                "or wait for it to finish before switching agents."
            )
            return

        if not name:
            # Show list of agents
            lines = ["**Available Agents:**\n"]
            for agent in self._agents:
                active = " (active)" if agent == self._active_agent else ""
                desc = f" - {agent.description}" if agent.description else ""
                lines.append(f"- `{agent.name}`{desc}{active}")
            lines.append("\nUse `/agent <name>` to switch agents.")
            response.complete("\n".join(lines))
        else:
            # Try to select the agent
            found = None
            for agent in self._agents:
                if agent.name.lower() == name.lower():
                    found = agent
                    break

            if found:
                self.set_active_agent(found)
                response.complete(f"Switched to agent: **{found.name}**")
            else:
                names = ", ".join(f"`{a.name}`" for a in self._agents)
                response.error(f"Agent `{name}` not found. Available: {names}")

    async def _cmd_help(self) -> None:
        """Show help."""
        response = self.conversation.add_bot_response()
        help_text = "**Available Commands:**\n\n"
        for cmd in self.commands.all():
            help_text += f"- `{cmd.usage}` - {cmd.description}\n"
        help_text += "\n**Keyboard Shortcuts:**\n\n"
        help_text += "- `Enter` - Send message\n"
        help_text += "- `Ctrl+Enter` - New line\n"
        help_text += "- `Up/Down` - Navigate input history\n"
        help_text += "- `Escape` - Abort current operation\n"
        help_text += "- `Tab` - Complete command\n"
        if self._active_agent:
            help_text += f"\n**Active Agent:** {self._active_agent.name}\n"
        response.complete(help_text)

    async def _cmd_export(self, filename: str = "") -> None:
        """Export conversation to a file."""
        if not filename:
            filename = "conversation.json"

        response = self.conversation.add_bot_response()
        try:
            write_conversation_archive(self.conversation.messages, filename)
            response.complete(f"Conversation exported to `{filename}`")
        except OSError as e:
            response.error(f"Failed to export conversation: {e}")

    async def _cmd_import(self, filename: str = "") -> None:
        """Import conversation from a file."""
        if not filename:
            filename = "conversation.json"

        try:
            data = read_conversation_archive(filename)
            self.conversation.clear()

            for msg in data:
                if msg["role"] == "user":
                    self.conversation.add_user_message(msg["content"])
                elif msg["role"] == "assistant":
                    response = self.conversation.add_bot_response()
                    if "errors" in msg:
                        for err in msg["errors"]:
                            response.add_error(err["label"], err.get("detail", ""))
                    if "response" in msg:
                        response.complete(msg["response"])
                    if "token_usage" in msg:
                        response.set_token_usage(msg["token_usage"])

            info = self.conversation.add_bot_response()
            info.complete(f"Conversation imported from `{filename}`")
        except FileNotFoundError:
            response = self.conversation.add_bot_response()
            response.error(f"File not found: `{filename}`")
        except ValueError as e:
            response = self.conversation.add_bot_response()
            response.error(f"Invalid JSON: {e}")

    def copy_to_clipboard(self, text: str) -> None:
        """Copy text to the system clipboard."""
        if not text:
            raise ValueError("Nothing to copy.")

        command = self._clipboard_command()
        if command:
            subprocess.run(
                command,
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return

        # OSC52 works in many terminal emulators and over SSH/tmux setups.
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        sys.stdout.write(f"\033]52;c;{encoded}\a")
        sys.stdout.flush()

    def _clipboard_command(self) -> list[str] | None:
        """Return the first available clipboard command for this platform."""
        candidates: list[list[str]]
        if sys.platform == "darwin":
            candidates = [["pbcopy"]]
        elif os.name == "nt":
            candidates = [["clip"]]
        else:
            candidates = [
                ["wl-copy"],
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ]

        for command in candidates:
            if shutil.which(command[0]):
                return command
        return None

    def action_copy_conversation(self) -> None:
        """Copy the current conversation transcript."""
        response = self.conversation.add_bot_response()
        try:
            self.copy_to_clipboard(conversation_to_text(self.conversation.messages[:-1]))
            response.complete("Conversation copied to clipboard.")
        except Exception as e:
            response.error(f"Failed to copy conversation: {e}")

    def on_message(
        self,
        handler: MessageHandler,
    ) -> MessageHandler:
        """Decorator to register a message handler.

        Example:
            @ui.on_message
            async def handle(message: str, response: BotResponse):
                response.thinking("Processing...")
                response.complete("Done!")
        """
        self._message_handler = handler
        return handler

    def on_busy_message(
        self,
        handler: BusyMessageHandler,
    ) -> BusyMessageHandler:
        """Register a handler for input submitted while another run is active."""
        self._busy_message_handler = handler
        return handler

    def on_cancel(self, handler: CancelHandler) -> CancelHandler:
        """Register a callback used to request cancellation."""
        self._cancel_handler = handler
        return handler

    def compose(self) -> ComposeResult:
        """Compose the UI."""
        yield ActiveWorkItemHeader(
            self._active_work_item_id,
            self._active_work_item_title,
            self._active_work_item_status,
            self._active_work_item_input_tokens,
            self._active_work_item_output_tokens,
        )
        yield ConversationView(self.conversation, settings=self._settings)
        yield ApprovalDialog()
        yield ChatInput(self.commands.all())

    def on_mount(self) -> None:
        """Focus the chat input when the app is ready."""
        self._focus_input()

    def on_click(self, event) -> None:
        """Return focus to the chat input after clicks outside approval."""
        self._focus_input()

    def _focus_input(self) -> None:
        """Keep keyboard input directed at the chat input when possible."""
        try:
            dialog = self.query_one(ApprovalDialog)
            if dialog.has_class("visible"):
                return
        except Exception:
            pass

        try:
            chat_input = self.query_one(ChatInput)
            self.call_after_refresh(chat_input.text_area.focus)
        except Exception:
            pass

    def _on_conversation_update(self) -> None:
        """Handle conversation updates."""
        try:
            view = self.query_one(ConversationView)
            view.refresh_conversation()
        except Exception:
            pass  # View may not exist yet
        self._focus_input()

    async def request_tool_approval(self, tool_name: str, args: dict) -> str:
        """Request user approval for a tool call.

        Returns "yes", "no", or "session".
        """
        self._pending_approval_event = asyncio.Event()
        self._approval_result = None

        # Show the dialog
        try:
            dialog = self.query_one(ApprovalDialog)
            dialog.show(tool_name, args)
            dialog.focus()
        except Exception:
            return "yes"  # Dialog not available, auto-approve

        # Wait for user response
        await self._pending_approval_event.wait()
        return self._approval_result or "no"

    def on_approval_dialog_response(self, event: ApprovalDialog.Response) -> None:
        """Handle approval dialog response."""
        self._approval_result = event.result
        if self._pending_approval_event:
            self._pending_approval_event.set()

        # Refocus input
        self._focus_input()

    def _reject_pending_approval(self) -> bool:
        """Reject a visible approval dialog and unblock the waiting tool call."""
        try:
            dialog = self.query_one(ApprovalDialog)
            if not dialog.has_class("visible"):
                return False
            dialog.hide()
        except Exception:
            return False

        self._approval_result = "no"
        if self._pending_approval_event:
            self._pending_approval_event.set()
        return True

    def action_abort(self) -> None:
        """Abort the current operation."""
        approval_rejected = self._reject_pending_approval()
        if self._current_task and not self._current_task.done():
            if self._cancel_handler:
                self._cancel_handler()
            if self._current_response:
                self._current_response.cancel()
        elif approval_rejected and self._cancel_handler:
            self._cancel_handler()
        self._focus_input()

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle message submission."""
        if self._current_task and not self._current_task.done():
            await self._handle_busy_message(event.value)
            self._focus_input()
            return

        self._start_message_run(event.value)
        self._focus_input()

    async def _handle_busy_message(self, message: str) -> None:
        """Forward busy-time input to the application layer."""
        self.conversation.add_user_message(message)
        response = self.conversation.add_bot_response()
        if not self._busy_message_handler:
            response.error("No busy message handler configured.")
            return
        try:
            await self._busy_message_handler(message, response)
        except Exception as e:
            if not response.is_cancelled:
                response.error(str(e))

    def _start_message_run(self, message: str, *, add_user_message: bool = True) -> None:
        """Create a bot response and start handling a user message."""
        if add_user_message:
            self.conversation.add_user_message(message)
        response = self.conversation.add_bot_response()

        if not self._message_handler:
            response.error("No message handler configured.")
            return

        self._current_response = response
        self._current_task = asyncio.create_task(
            self._run_handler(message, response)
        )

    async def _run_handler(self, message: str, response: BotResponse) -> None:
        """Run the message handler with cancellation support."""
        try:
            await self._message_handler(message, response)
        except asyncio.CancelledError:
            # Handler was cancelled, response already marked as cancelled
            pass
        except Exception as e:
            if not response.is_cancelled:
                response.error(str(e))
        finally:
            self._current_task = None
            self._current_response = None
            self._focus_input()

    async def on_chat_input_command_selected(
        self,
        event: ChatInput.CommandSelected,
    ) -> None:
        """Handle command selection."""
        cmd = event.command
        if cmd.handler:
            try:
                if event.args:
                    await cmd.handler(event.args)
                else:
                    await cmd.handler()
            except Exception as e:
                response = self.conversation.add_bot_response()
                response.error(f"Command error: {e}")
            finally:
                self._focus_input()
