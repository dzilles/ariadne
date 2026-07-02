"""Ariadne TUI - Enhanced terminal interface for the Ariadne lifecycle engine.

This module integrates the sophisticated TUI library with the project's
V-Model agents (Orchestrator, Requirements, Engineer).
"""

import logging
from typing import Any

from src.ariadne.ui import ChatUI, Agent, BotResponse
from src.ariadne.application.commands import APPLICATION_COMMANDS
from src.ariadne.application.controller import AriadneApplicationController
from src.ariadne.application.settings_store import update_user_setting
from src.ariadne.application.ui_contract import (
    CommandResult,
    TokenUsage,
    ToolEvent,
    WorkItemInfo,
)
from src.ariadne.ui.commands import CommandRegistry, create_default_commands
from src.ariadne.ui.conversation_archive import (
    conversation_to_text,
    last_bot_response_text,
)
from src.ariadne.infrastructure.logging import setup_logging
from src.ariadne.ui.message_display import (
    ActivityAnimation,
    DisplayMode,
    format_tool_call_detail,
    tool_event_rule,
)
from src.ariadne.ui.run_renderer import render_run_event

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Silence verbose loggers for a clean chat interface."""
    loggers_to_silence = [
        "httpx",
        "httpcore",
        "google",
        "google_genai._api_client",
        "urllib3",
        "src.ariadne.llm.factory",
        "src.ariadne.config.settings",
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
        from src.ariadne.config.settings import settings

        self.settings = settings
        self.controller = AriadneApplicationController()
        self._active_tool_response: BotResponse | None = None

        # Create Agent wrappers for UI
        agents = [
            Agent(
                name=agent.name,
                description=agent.description,
            )
            for agent in self.controller.list_agents()
        ]

        # Create custom command registry
        commands = self._create_commands()

        # Initialize the ChatUI
        self.ui = ChatUI(
            title="Ariadne",
            commands=commands,
            agents=agents,
            settings=self.settings,
        )

        # Register event handlers
        self._register_handlers()

    def _create_commands(self) -> CommandRegistry:
        """Create the command registry with project-specific commands."""
        commands = create_default_commands()

        for command in APPLICATION_COMMANDS:
            commands.add(command.name, command.description, command.args)
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
            await tui._handle_user_message(message, response)

        @self.ui.on_busy_message
        async def on_busy_message(message: str, response: BotResponse) -> None:
            await tui._handle_user_message(message, response)

        self.ui.on_cancel(self.controller.cancel_active_run)

        # Custom command handlers
        self.ui.commands.set_handler("save", self._cmd_save)
        self.ui.commands.set_handler("load", self._cmd_load)
        self.ui.commands.set_handler("history", self._cmd_history)
        self.ui.commands.set_handler("clearhistory", self._cmd_clear_history)
        self.ui.commands.set_handler("secret", self._cmd_secret)
        self.ui.commands.set_completions("secret", self._get_secret_completions)
        self.ui.commands.set_handler("copy", self._cmd_copy)
        self.ui.commands.set_completions("copy", ["last", "all"])

        self.controller.bind_runtime_callbacks(
            approval_callback=self.ui.request_tool_approval,
            tool_event_callback=self._on_tool_event,
            active_work_item_callback=self._on_active_work_item_changed,
            token_usage_callback=self._on_active_work_item_token_usage,
            tool_approval_enabled=self.settings.tool_approval,
        )

        # Settings change handler - persist and reinitialize agents
        @self.ui.on_settings_change
        def on_settings_change(field_name: str, value: Any) -> None:
            update_user_setting(field_name, value)

            # Handle tool_approval setting change
            if field_name == "tool_approval":
                tui.controller.set_tool_approval_enabled(value)
                return

            # Clear and reinitialize agents for other settings
            tui.controller.clear_agent_cache()
            active_agent = tui.ui.get_active_agent()
            if active_agent:
                tui._switch_agent(active_agent)

    async def _handle_user_message(self, message: str, response: BotResponse) -> None:
        """Submit a user message to the application controller."""
        def emit(event) -> None:
            if event.type == "run_started":
                self._active_tool_response = response
            render_run_event(response, event)
            if (
                event.type in {"run_finished", "cancelled"}
                and self._active_tool_response is response
            ):
                self._active_tool_response = None

        try:
            await self.controller.handle_user_message(
                message,
                emit=emit,
                is_cancelled=lambda: response.is_cancelled,
            )
        finally:
            if self._active_tool_response is response:
                self._active_tool_response = None

    def _on_tool_event(self, event: ToolEvent) -> None:
        """Render tool execution events."""
        response = self._active_tool_response
        if not response:
            return

        # Truncate result for display
        display_result = event.result
        if len(display_result) > 100:
            display_result = display_result[:100] + "..."

        rule = tool_event_rule(event.status)
        if rule.mode == DisplayMode.HIDDEN:
            return

        tool_detail = format_tool_call_detail(event.name, event.args)
        if event.status == "start":
            response.activity(
                f"Tool: {event.name}",
                tool_detail,
                mode=rule.mode,
                animation=rule.animation,
            )
            response.tool(event.name, tool_detail, animation=rule.animation)
        elif event.status == "success":
            response.clear_status()
            response.activity(
                f"Tool: {event.name}",
                display_result,
                mode=rule.mode,
                animation=rule.animation,
            )
            if self._active_tool_response is response and not response.is_cancelled:
                response.thinking(
                    "Processing tool result...",
                    animation=ActivityAnimation.WAVE,
                )
        elif event.status in {"error", "cancelled"}:
            response.clear_status()
            response.tool_error(event.name, display_result)
            if self._active_tool_response is response and not response.is_cancelled:
                response.thinking(
                    "Processing tool result...",
                    animation=ActivityAnimation.WAVE,
                )

    def _on_active_work_item_changed(self, work_item: WorkItemInfo | None) -> None:
        """Render active work item changes."""
        if not work_item:
            self._set_active_work_item_header(None, None, None)
            return
        self._set_active_work_item_header(work_item.id, work_item.title, work_item.status)

    def _on_active_work_item_token_usage(self, usage: TokenUsage) -> None:
        """Add model token usage to the active work item header."""
        usage_dict = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        }
        try:
            self.ui.call_from_thread(self.ui.add_active_work_item_token_usage, usage_dict)
        except Exception:
            self.ui.add_active_work_item_token_usage(usage_dict)

    def _set_active_work_item_header(
        self,
        work_item_id: str | None,
        title: str | None,
        status: str | None,
    ) -> None:
        """Update the UI header from either the UI thread or an agent thread."""
        try:
            self.ui.call_from_thread(
                self.ui.set_active_work_item_info,
                work_item_id,
                title,
                status,
            )
        except Exception:
            self.ui.set_active_work_item_info(work_item_id, title, status)

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
                      If None, only log the error.
            log: If True, also log the error. Set False for user-facing only.
        """
        if log:
            logger.error(message)
        if response:
            response.error(message)

    def _complete_command(self, response: BotResponse, result: CommandResult) -> None:
        """Render an application command result in the current conversation."""
        if result.is_error:
            self._report_error(result.message, response)
        else:
            response.complete(result.message)

    def _switch_agent(self, agent: Agent | None) -> None:
        """Switch to a different agent.

        Args:
            agent: The Agent to switch to, or None to clear
        """
        result = self.controller.switch_agent(agent.name if agent else None)
        if result.is_error:
            self._report_error(result.message)

    async def _cmd_save(self) -> None:
        """Save chat history for current agent."""
        response = self.ui.conversation.add_bot_response()
        self._complete_command(response, self.controller.save_chat_history())

    async def _cmd_load(self) -> None:
        """Load chat history for current agent."""
        response = self.ui.conversation.add_bot_response()
        self._complete_command(response, self.controller.load_chat_history())

    async def _cmd_history(self) -> None:
        """Show history status for all agents."""
        response = self.ui.conversation.add_bot_response()
        self._complete_command(response, self.controller.get_history_status())

    async def _cmd_clear_history(self) -> None:
        """Clear saved history for current agent."""
        response = self.ui.conversation.add_bot_response()
        self._complete_command(response, self.controller.clear_chat_history())

    def _get_secret_completions(self, context: str = "") -> list[str]:
        """Get available secret key names for completions."""
        return self.controller.get_secret_completions(context)

    def _clear_agent_cache(self) -> None:
        """Clear cached agent instances so they get re-created with new settings."""
        self.controller.clear_agent_cache()

    async def _cmd_secret(self, args: str = "") -> None:
        """Manage API keys in secure vault."""
        response = self.ui.conversation.add_bot_response()
        self._complete_command(response, self.controller.manage_secret(args))

    async def _cmd_copy(self, args: str = "") -> None:
        """Copy response or conversation content to clipboard."""
        response = self.ui.conversation.add_bot_response()
        mode = (args or "last").strip().lower()

        if mode not in {"last", "all"}:
            self._report_error("Usage: /copy [last|all]", response, log=False)
            return

        messages = self.ui.conversation.messages[:-1]
        content = (
            conversation_to_text(messages)
            if mode == "all"
            else last_bot_response_text(messages)
        )
        if not content:
            self._report_error("No content to copy.", response, log=False)
            return

        try:
            self.ui.copy_to_clipboard(content)
            response.complete(
                "Conversation copied to clipboard."
                if mode == "all"
                else "Last response copied to clipboard."
            )
        except Exception as e:
            self._report_error(f"Failed to copy: {e}", response)

    def run(self) -> None:
        """Run the TUI application."""
        self.controller.load_initial_agent()

        # Add welcome message showing agent status
        welcome = self.ui.conversation.add_bot_response()
        if self.controller.current_agent:
            welcome.info(
                f"**Ariadne TUI**\n\n"
                f"Active agent: **{self.controller.current_agent_name}**\n\n"
                f"Type a message to chat, or use `/help` for commands."
            )
        elif self.controller.init_error:
            welcome.error(
                f"Failed to initialize agent: {self.controller.init_error}\n\n"
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
