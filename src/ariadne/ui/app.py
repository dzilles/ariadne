"""Main ChatUI application."""

import asyncio
from dataclasses import dataclass
from typing import Callable, Awaitable, Any, get_args, get_origin
from pathlib import Path
from enum import Enum
import json

from textual.app import App, ComposeResult
from textual.binding import Binding

from .message import Conversation, BotResponse
from .commands import CommandRegistry, create_default_commands
from .widgets import ActiveWorkItemHeader, ChatInput, ConversationView, ApprovalDialog
from src.ariadne.runtime import run_manager

# Try to import Pydantic (optional dependency)
try:
    from pydantic import BaseModel
    PYDANTIC_AVAILABLE = True
except ImportError:
    BaseModel = None
    PYDANTIC_AVAILABLE = False


# Type alias for message handlers
MessageHandler = Callable[[str, BotResponse], Awaitable[None]]


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

        # Settings command (only if Pydantic model provided)
        if self._settings is not None and PYDANTIC_AVAILABLE:
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
        if not self._settings or not PYDANTIC_AVAILABLE:
            return []

        parts = context.split()

        if len(parts) == 0 or (len(parts) == 1 and not context.endswith(" ")):
            # Still typing first argument: show field names
            return list(self._settings.model_fields.keys())

        # First argument complete, show choices for that field
        field_name = parts[0]
        if field_name in self._settings.model_fields:
            field_info = self._settings.model_fields[field_name]
            choices = self._get_field_choices(field_info)
            if choices:
                return choices

        return []

    def _get_field_type_name(self, field_info) -> str:
        """Get a human-readable type name for a field."""
        annotation = field_info.annotation
        origin = get_origin(annotation)

        # Handle Optional types
        if origin is type(None) or str(origin) == "typing.Union":
            args = get_args(annotation)
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                annotation = non_none[0]
                origin = get_origin(annotation)

        # Handle Literal
        if str(origin) == "typing.Literal":
            choices = get_args(annotation)
            return f"Literal{list(choices)}"

        # Handle Enum
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            choices = [e.value for e in annotation]
            return f"Enum{choices}"

        # Handle basic types
        if annotation is str:
            return "str"
        elif annotation is int:
            return "int"
        elif annotation is float:
            return "float"
        elif annotation is bool:
            return "bool"
        elif origin is list:
            return "list"
        elif origin is dict:
            return "dict"

        return str(annotation).replace("typing.", "")

    def _get_field_choices(self, field_info) -> list[str] | None:
        """Get available choices for a field (for Literal/Enum/bool types)."""
        annotation = field_info.annotation
        origin = get_origin(annotation)

        # Handle Optional types
        if origin is type(None) or str(origin) == "typing.Union":
            args = get_args(annotation)
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                annotation = non_none[0]
                origin = get_origin(annotation)

        # Handle Literal
        if str(origin) == "typing.Literal":
            return [str(c) for c in get_args(annotation)]

        # Handle Enum
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            return [str(e.value) for e in annotation]

        # Handle bool
        if annotation is bool:
            return ["true", "false"]

        return None

    def _parse_value(self, field_info, value_str: str) -> Any:
        """Parse a string value to the appropriate type for a field."""
        annotation = field_info.annotation
        origin = get_origin(annotation)

        # Handle Optional types
        if origin is type(None) or str(origin) == "typing.Union":
            args = get_args(annotation)
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                annotation = non_none[0]
                origin = get_origin(annotation)

        # Handle Literal
        if str(origin) == "typing.Literal":
            choices = get_args(annotation)
            # Try to match the value
            for choice in choices:
                if str(choice).lower() == value_str.lower():
                    return choice
            raise ValueError(f"Must be one of: {list(choices)}")

        # Handle Enum
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            for e in annotation:
                if str(e.value).lower() == value_str.lower() or e.name.lower() == value_str.lower():
                    return e
            choices = [e.value for e in annotation]
            raise ValueError(f"Must be one of: {choices}")

        # Handle basic types
        if annotation is bool:
            if value_str.lower() in ("true", "1", "yes", "on"):
                return True
            elif value_str.lower() in ("false", "0", "no", "off"):
                return False
            raise ValueError("Must be true or false")
        elif annotation is int:
            return int(value_str)
        elif annotation is float:
            return float(value_str)
        elif annotation is str:
            return value_str

        # For complex types, try JSON parsing
        try:
            return json.loads(value_str)
        except json.JSONDecodeError:
            return value_str

    async def _cmd_settings(self, args: str = "") -> None:
        """Show or change settings."""
        response = self.conversation.add_bot_response()

        if not self._settings:
            response.error("No settings configured.")
            return

        parts = args.split(maxsplit=1)
        field_name = parts[0] if parts else ""
        new_value = parts[1] if len(parts) > 1 else ""

        if not field_name:
            # Show all settings
            lines = ["**Settings:**\n"]
            for name, field_info in self._settings.model_fields.items():
                current = getattr(self._settings, name)
                type_name = self._get_field_type_name(field_info)
                desc = field_info.description or ""

                # Format current value
                if isinstance(current, Enum):
                    current_str = current.value
                else:
                    current_str = repr(current)

                lines.append(f"- `{name}` = {current_str}")
                if desc:
                    lines.append(f"  *{desc}*")
                lines.append(f"  Type: {type_name}")
                lines.append("")

            lines.append("Use `/settings <field> <value>` to change a setting.")
            response.complete("\n".join(lines))
            return

        # Check if field exists
        if field_name not in self._settings.model_fields:
            available = ", ".join(f"`{n}`" for n in self._settings.model_fields.keys())
            response.error(f"Unknown setting `{field_name}`. Available: {available}")
            return

        field_info = self._settings.model_fields[field_name]

        if not new_value:
            # Show specific field details
            current = getattr(self._settings, field_name)
            type_name = self._get_field_type_name(field_info)
            desc = field_info.description or "No description"
            choices = self._get_field_choices(field_info)

            if isinstance(current, Enum):
                current_str = current.value
            else:
                current_str = repr(current)

            lines = [
                f"**{field_name}**\n",
                f"Current value: {current_str}",
                f"Type: {type_name}",
                f"Description: {desc}",
            ]
            if choices:
                lines.append(f"Choices: {', '.join(choices)}")
            lines.append(f"\nUse `/settings {field_name} <value>` to change.")
            response.complete("\n".join(lines))
            return

        # Change the setting
        try:
            parsed_value = self._parse_value(field_info, new_value)
            old_value = getattr(self._settings, field_name)
            setattr(self._settings, field_name, parsed_value)

            # Notify callback
            if self._on_settings_change:
                self._on_settings_change(field_name, parsed_value)

            if isinstance(parsed_value, Enum):
                new_str = parsed_value.value
            else:
                new_str = repr(parsed_value)

            response.info(f"Changed `{field_name}` to {new_str}")
        except (ValueError, TypeError) as e:
            response.error(f"Invalid value: {e}")

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

        data = []
        for msg in self.conversation.messages:
            if hasattr(msg, "content") and isinstance(msg.content, str):
                data.append({"role": "user", "content": msg.content})
            elif isinstance(msg, BotResponse):
                entry = {"role": "assistant"}
                if msg.response:
                    entry["response"] = msg.response
                if msg.token_usage:
                    entry["token_usage"] = msg.token_usage
                if msg.errors:
                    entry["errors"] = [
                        {"label": e.label, "detail": e.detail}
                        for e in msg.errors
                    ]
                data.append(entry)

        Path(filename).write_text(json.dumps(data, indent=2))

        response = self.conversation.add_bot_response()
        response.complete(f"Conversation exported to `{filename}`")

    async def _cmd_import(self, filename: str = "") -> None:
        """Import conversation from a file."""
        if not filename:
            filename = "conversation.json"

        try:
            data = json.loads(Path(filename).read_text())
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
        except json.JSONDecodeError as e:
            response = self.conversation.add_bot_response()
            response.error(f"Invalid JSON: {e}")

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

    def _on_conversation_update(self) -> None:
        """Handle conversation updates."""
        try:
            view = self.query_one(ConversationView)
            view.refresh_conversation()
        except Exception:
            pass  # View may not exist yet

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
        try:
            chat_input = self.query_one(ChatInput)
            chat_input.text_area.focus()
        except Exception:
            pass

    def action_abort(self) -> None:
        """Abort the current operation."""
        # Don't abort if approval dialog is visible (escape dismisses dialog instead)
        try:
            dialog = self.query_one(ApprovalDialog)
            if dialog.has_class("visible"):
                return
        except Exception:
            pass

        if self._current_task and not self._current_task.done():
            run_manager.request_cancel()
            if self._current_response:
                self._current_response.cancel()

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle message submission."""
        if self._current_task and not self._current_task.done():
            active_run = run_manager.get_active_run()
            self.conversation.add_user_message(event.value)
            response = self.conversation.add_bot_response()
            if active_run:
                response.info(
                    "A run is already active. Press `Escape` to request cancellation, "
                    "then wait for the current tool or model step to stop before sending a new message."
                )
            else:
                response.info(
                    "A run is still finishing. Wait for it to complete before sending a new message."
                )
            return

        self.conversation.add_user_message(event.value)
        response = self.conversation.add_bot_response()

        if self._message_handler:
            self._current_response = response
            self._current_task = asyncio.create_task(
                self._run_handler(event.value, response)
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
