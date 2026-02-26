"""Ariadne TUI - Enhanced terminal interface for the Ariadne lifecycle engine.

This module integrates the sophisticated TUI library with the project's
V-Model agents (Product Owner, Requirements, Engineer).
"""

import json
import logging
import os
from typing import Any

from src.tui import ChatUI, Agent, BotResponse
from src.tui.agent_adapter import (
    AGENT_CLASSES,
    AGENT_DESCRIPTIONS,
    handle_message,
    get_agent_names,
)
from src.tui.history import (
    save_history,
    load_history,
    clear_history as clear_history_file,
    has_history,
    get_history_summary,
)
from src.configuration.vault import Vault
from src.tui.commands import CommandRegistry, create_default_commands
from src.configuration.config import settings
from src.configuration.logging_config import setup_logging
from src.tools.tool_wrapper import (
    set_approval_callback,
    set_tool_notify_callback,
    enable_approval,
    reset_session_approval,
)

logger = logging.getLogger(__name__)

# Settings persistence
SETTINGS_DIR = ".ariadne"
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "user_settings.json")


def _load_user_settings() -> dict:
    """Load user settings from file."""
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load user settings: {e}")
        return {}


def _save_user_settings(data: dict) -> bool:
    """Save user settings to file."""
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save user settings: {e}")
        return False


def configure_logging() -> None:
    """Silence verbose loggers for a clean chat interface."""
    loggers_to_silence = [
        "httpx",
        "httpcore",
        "google",
        "google_genai._api_client",
        "urllib3",
        "src.configuration.llm_factory",
        "src.configuration.config",
    ]
    for logger_name in loggers_to_silence:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


class AriadneTUI:
    """Main application integrating TUI with Ariadne agents."""

    def __init__(self) -> None:
        """Initialize the Ariadne TUI application."""
        # Set up logging
        setup_logging()
        configure_logging()

        # Create Agent wrappers for UI
        agents = [
            Agent(
                name=name,
                description=AGENT_DESCRIPTIONS.get(name, f"{name} Agent"),
            )
            for name in get_agent_names()
        ]

        # Create custom command registry
        commands = self._create_commands()

        # Initialize the ChatUI
        self.ui = ChatUI(
            title="Ariadne",
            commands=commands,
            agents=agents,
            settings=settings,
        )

        # Agent instance cache
        self._agent_instances: dict[str, Any] = {}
        self._current_agent: Any = None
        self._current_agent_name: str | None = None
        self._init_error: str | None = None

        # Register event handlers
        self._register_handlers()

    def _create_commands(self) -> CommandRegistry:
        """Create the command registry with project-specific commands."""
        commands = create_default_commands()

        # Add project-specific commands
        commands.add("save", "Save chat history for current agent")
        commands.add("load", "Load chat history for current agent")
        commands.add("history", "Show history status for all agents")
        commands.add("clearhistory", "Clear saved history for current agent")
        commands.add("secret", "Manage API keys in secure vault", "[key] [value]")
        commands.add("copy", "Copy last response to clipboard")
        return commands

    def _register_handlers(self) -> None:
        """Register all event handlers."""
        # Store reference to self for closures
        tui = self

        # Agent change handler
        @self.ui.on_agent_change
        def on_agent_change(agent: Agent | None) -> None:
            tui._switch_agent(agent)

        # Message handler
        @self.ui.on_message
        async def on_message(message: str, response: BotResponse) -> None:
            if tui._current_agent:
                await handle_message(message, response, tui._current_agent)
            elif tui._init_error:
                # Error already logged during init, just show in TUI
                tui._report_error(tui._init_error, response, log=False)
            else:
                tui._report_error("No agent selected. Use /agent to select one.", response)

        # Custom command handlers
        self.ui.commands.set_handler("save", self._cmd_save)
        self.ui.commands.set_handler("load", self._cmd_load)
        self.ui.commands.set_handler("history", self._cmd_history)
        self.ui.commands.set_handler("clearhistory", self._cmd_clear_history)
        self.ui.commands.set_handler("secret", self._cmd_secret)
        self.ui.commands.set_completions("secret", self._get_secret_completions)
        self.ui.commands.set_handler("copy", self._cmd_copy)

        # Set up tool approval callback and initialize from settings
        set_approval_callback(self.ui.request_tool_approval)
        set_tool_notify_callback(self._on_tool_notify)
        enable_approval(settings.tool_approval)

        # Settings change handler - persist and reinitialize agents
        @self.ui.on_settings_change
        def on_settings_change(field_name: str, value: Any) -> None:
            # Save to persistent storage
            user_settings = _load_user_settings()
            user_settings[field_name] = value
            _save_user_settings(user_settings)

            # Handle tool_approval setting change
            if field_name == "tool_approval":
                enable_approval(value)
                reset_session_approval()
                return

            # Clear and reinitialize agents for other settings
            tui._clear_agent_cache()
            active_agent = tui.ui.get_active_agent()
            if active_agent:
                tui._switch_agent(active_agent)

    def _on_tool_notify(self, tool_name: str, status: str, args: dict, result: str) -> None:
        """Handle tool execution notifications."""
        # Find the current bot response (last one in conversation)
        response = None
        for msg in reversed(self.ui.conversation.messages):
            if isinstance(msg, BotResponse):
                response = msg
                break

        if not response:
            return

        # Truncate result for display
        display_result = result
        if len(display_result) > 100:
            display_result = display_result[:100] + "..."

        if status == "start":
            response.tool(tool_name, "Running...")
        elif status == "success":
            response.tool_success(tool_name, display_result)
        elif status == "error":
            response.tool_error(tool_name, display_result)

    def _report_error(
        self,
        message: str,
        response: BotResponse | None = None,
        log: bool = True,
    ) -> None:
        """Report error to log and/or TUI.

        Args:
            message: The error message
            response: If provided, show error immediately in this response.
                      If None, store in _init_error for later display.
            log: If True, also log the error. Set False for user-facing only.
        """
        if log:
            logger.error(message)
        if response:
            response.error(message)
        else:
            self._init_error = message

    def _switch_agent(self, agent: Agent | None) -> None:
        """Switch to a different agent.

        Args:
            agent: The Agent to switch to, or None to clear
        """
        # Reset session approval when switching agents
        reset_session_approval()

        if agent is None:
            self._current_agent = None
            self._current_agent_name = None
            return

        name = agent.name
        self._init_error = None

        # Check if we already have this agent instantiated
        if name not in self._agent_instances:
            try:
                agent_class = AGENT_CLASSES.get(name)
                if agent_class:
                    self._agent_instances[name] = agent_class()
                else:
                    self._report_error(f"Unknown agent class: {name}")
                    return
            except Exception as e:
                self._report_error(f"Failed to initialize {name}: {e}")
                return

        self._current_agent = self._agent_instances.get(name)
        self._current_agent_name = name

    async def _cmd_save(self) -> None:
        """Save chat history for current agent."""
        response = self.ui.conversation.add_bot_response()

        if not self._current_agent or not self._current_agent_name:
            self._report_error("No agent selected. Use /agent first.", response)
            return

        if save_history(self._current_agent, self._current_agent_name):
            response.complete(
                f"Chat history saved for **{self._current_agent_name}**"
            )
        else:
            self._report_error("Failed to save chat history", response)

    async def _cmd_load(self) -> None:
        """Load chat history for current agent."""
        response = self.ui.conversation.add_bot_response()

        if not self._current_agent or not self._current_agent_name:
            self._report_error("No agent selected. Use /agent first.", response)
            return

        if not has_history(self._current_agent_name):
            response.complete(
                f"No saved history found for **{self._current_agent_name}**"
            )
            return

        if load_history(self._current_agent, self._current_agent_name):
            summary = get_history_summary(self._current_agent_name)
            count = summary.get("message_count", 0) if summary else 0
            response.complete(
                f"Loaded {count} messages for **{self._current_agent_name}**"
            )
        else:
            self._report_error("Failed to load chat history", response)

    async def _cmd_history(self) -> None:
        """Show history status for all agents."""
        response = self.ui.conversation.add_bot_response()

        lines = ["**Chat History Status:**\n"]

        for name in get_agent_names():
            summary = get_history_summary(name)
            active = " (active)" if name == self._current_agent_name else ""

            if summary:
                count = summary.get("message_count", 0)
                lines.append(f"- `{name}`{active}: {count} messages saved")
            else:
                lines.append(f"- `{name}`{active}: No saved history")

        lines.append("\nUse `/save` to save or `/load` to restore history.")
        response.complete("\n".join(lines))

    async def _cmd_clear_history(self) -> None:
        """Clear saved history for current agent."""
        response = self.ui.conversation.add_bot_response()

        if not self._current_agent_name:
            self._report_error("No agent selected. Use /agent first.", response)
            return

        # Clear the file
        clear_history_file(self._current_agent_name)

        # Also clear the agent's in-memory history
        if self._current_agent and hasattr(self._current_agent, "clear_history"):
            self._current_agent.clear_history()

        response.complete(
            f"History cleared for **{self._current_agent_name}**"
        )

    def _get_secret_completions(self, context: str = "") -> list[str]:
        """Get available secret key names for completions."""
        keys = Vault.list_managed_keys()
        parts = context.split()

        # If first arg complete, offer "delete" as second arg option
        if len(parts) >= 1 and context.endswith(" "):
            return ["delete"]

        return keys

    def _clear_agent_cache(self) -> None:
        """Clear cached agent instances so they get re-created with new settings."""
        self._agent_instances.clear()
        self._current_agent = None
        self._current_agent_name = None

    async def _cmd_secret(self, args: str = "") -> None:
        """Manage API keys in secure vault."""
        response = self.ui.conversation.add_bot_response()

        parts = args.split(maxsplit=1)
        key_name = parts[0].upper() if parts else ""
        value = parts[1] if len(parts) > 1 else ""

        managed_keys = Vault.list_managed_keys()

        if not key_name:
            # Show status of all managed keys
            lines = ["**Secret Vault Status:**\n"]
            for key in managed_keys:
                secret = Vault.get_secret(key)
                if secret:
                    # Show masked value
                    masked = secret[:4] + "..." + secret[-4:] if len(secret) > 8 else "****"
                    lines.append(f"- `{key}`: {masked}")
                else:
                    lines.append(f"- `{key}`: *not set*")
            lines.append("\n**Usage:**")
            lines.append("- `/secret KEY VALUE` - Set a secret")
            lines.append("- `/secret KEY delete` - Remove a secret")
            response.complete("\n".join(lines))
            return

        # Validate key name
        if key_name not in managed_keys:
            available = ", ".join(f"`{k}`" for k in managed_keys)
            self._report_error(
                f"Unknown key `{key_name}`. Available: {available}",
                response
            )
            return

        if not value:
            # Show specific key status
            secret = Vault.get_secret(key_name)
            if secret:
                masked = secret[:4] + "..." + secret[-4:] if len(secret) > 8 else "****"
                response.complete(f"`{key_name}` is set: {masked}")
            else:
                response.complete(f"`{key_name}` is not set.\n\nUse `/secret {key_name} YOUR_API_KEY` to set it.")
            return

        if value.lower() == "delete":
            # Delete the secret
            try:
                Vault.delete_secret(key_name)
                self._clear_agent_cache()
                response.complete(
                    f"Deleted `{key_name}` from vault.\n\n"
                    f"Use `/agent` to re-initialize an agent."
                )
            except Exception as e:
                self._report_error(f"Failed to delete secret: {e}", response)
            return

        # Set the secret
        try:
            Vault.set_secret(key_name, value)
            self._clear_agent_cache()
            response.complete(
                f"Saved `{key_name}` to secure vault.\n\n"
                f"Use `/agent` to re-initialize an agent with the new key."
            )
        except Exception as e:
            self._report_error(f"Failed to save secret: {e}", response)

    async def _cmd_copy(self) -> None:
        """Copy last response to clipboard."""
        response = self.ui.conversation.add_bot_response()

        # Find the last bot response with content
        last_content = None
        for msg in reversed(self.ui.conversation.messages):
            if isinstance(msg, BotResponse) and msg.response:
                last_content = msg.response
                break

        if not last_content:
            self._report_error("No response to copy.", response)
            return

        try:
            self.ui.copy_to_clipboard(last_content)
            response.complete("Copied to clipboard.")
        except Exception as e:
            self._report_error(f"Failed to copy: {e}", response)

    def run(self) -> None:
        """Run the TUI application."""
        # Initialize the first agent
        agents = self.ui.get_agents()
        if agents:
            self._switch_agent(agents[0])

            # Auto-load history if available
            if (
                self._current_agent_name
                and has_history(self._current_agent_name)
            ):
                load_history(self._current_agent, self._current_agent_name)
                logger.info(
                    f"Auto-loaded history for {self._current_agent_name}"
                )

        # Add welcome message showing agent status
        welcome = self.ui.conversation.add_bot_response()
        if self._current_agent:
            welcome.info(
                f"**Ariadne TUI**\n\n"
                f"Active agent: **{self._current_agent_name}**\n\n"
                f"Type a message to chat, or use `/help` for commands."
            )
        elif self._init_error:
            welcome.error(
                f"Failed to initialize agent: {self._init_error}\n\n"
                f"Check your configuration and try `/agent` to select one."
            )
        else:
            welcome.info(
                "**Ariadne TUI**\n\n"
                "No agent initialized. Use `/agent` to select one."
            )

        # Run the UI
        self.ui.run()


def main() -> None:
    """Entry point for the Ariadne TUI."""
    app = AriadneTUI()
    app.run()


if __name__ == "__main__":
    main()
