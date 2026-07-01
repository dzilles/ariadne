"""Application controller used by the terminal UI.

The controller owns Ariadne-specific coordination. The Textual UI should only
collect input and render output; it should not instantiate agents, read work
items, or know how command side effects are implemented.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal
from typing import Any

from .history import (
    HistoryError,
    HistoryFormatError,
    HistoryNotFoundError,
    clear_history,
    get_history_summary,
    load_history,
    save_history,
)

from .ui_contract import (
    AgentInfo,
    CommandResult,
    RunEvent,
    TokenUsage,
    ToolEvent,
    WorkItemInfo,
)

logger = logging.getLogger(__name__)


class AriadneApplicationController:
    """Coordinates application behavior behind a UI-neutral boundary."""

    def __init__(
        self,
        agent_classes: dict[str, Callable[[], Any]] | None = None,
        agent_descriptions: dict[str, str] | None = None,
        reset_session_approval_func: Callable[[], None] | None = None,
    ) -> None:
        if agent_classes is None or agent_descriptions is None:
            from .agents import AGENT_CLASSES, AGENT_DESCRIPTIONS

            agent_classes = AGENT_CLASSES if agent_classes is None else agent_classes
            agent_descriptions = (
                AGENT_DESCRIPTIONS if agent_descriptions is None else agent_descriptions
            )

        self._agent_classes = agent_classes
        self._agent_descriptions = agent_descriptions
        self._reset_session_approval = reset_session_approval_func
        self._agent_instances: dict[str, Any] = {}
        self._current_agent: Any = None
        self._current_agent_name: str | None = None
        self._init_error: str | None = None
        self._active_work_item_id: str | None = None
        self._tool_event_callback: Callable[[ToolEvent], None] | None = None
        self._active_work_item_callback: Callable[[WorkItemInfo | None], None] | None = None
        self._token_usage_callback: Callable[[TokenUsage], None] | None = None

    @property
    def current_agent_name(self) -> str | None:
        """Return the active agent name."""
        return self._current_agent_name

    @property
    def current_agent(self) -> Any:
        """Return the active agent instance."""
        return self._current_agent

    @property
    def init_error(self) -> str | None:
        """Return the last agent initialization error."""
        return self._init_error

    def list_agents(self) -> list[AgentInfo]:
        """Return all agents available to the UI."""
        return [
            AgentInfo(
                name=name,
                description=self._agent_descriptions.get(name, f"{name} Agent"),
            )
            for name in self._agent_classes
        ]

    def switch_agent(self, agent_name: str | None) -> CommandResult:
        """Switch the active agent by name."""
        self.reset_session_approval()

        if agent_name is None:
            self._current_agent = None
            self._current_agent_name = None
            return CommandResult("No agent selected.")

        self._init_error = None
        if agent_name not in self._agent_instances:
            try:
                agent_class = self._agent_classes.get(agent_name)
                if not agent_class:
                    return self._store_init_error(f"Unknown agent class: {agent_name}")
                self._agent_instances[agent_name] = agent_class()
            except Exception as e:
                return self._store_init_error(f"Failed to initialize {agent_name}: {e}")

        self._current_agent = self._agent_instances.get(agent_name)
        self._current_agent_name = agent_name
        return CommandResult(f"Switched to agent: **{agent_name}**")

    def _store_init_error(self, message: str) -> CommandResult:
        logger.error(message)
        self._init_error = message
        self._current_agent = None
        self._current_agent_name = None
        return CommandResult(message, is_error=True)

    def clear_agent_cache(self) -> None:
        """Clear cached agents after settings or secret changes."""
        self._agent_instances.clear()
        self._current_agent = None
        self._current_agent_name = None

    def bind_runtime_callbacks(
        self,
        *,
        approval_callback: Callable[[str, dict], Any],
        tool_event_callback: Callable[[ToolEvent], None],
        active_work_item_callback: Callable[[WorkItemInfo | None], None],
        token_usage_callback: Callable[[TokenUsage], None],
        tool_approval_enabled: bool,
    ) -> None:
        """Connect runtime callbacks to application-level UI events."""
        from src.ariadne.runtime.context import set_active_work_item_change_callback
        from src.ariadne.runtime.token_usage import set_active_work_item_token_usage_callback
        from src.ariadne.tools.tool_wrapper import (
            enable_approval,
            set_approval_callback,
            set_tool_notify_callback,
        )

        self._tool_event_callback = tool_event_callback
        self._active_work_item_callback = active_work_item_callback
        self._token_usage_callback = token_usage_callback

        set_approval_callback(approval_callback)
        set_tool_notify_callback(self._handle_tool_notify)
        set_active_work_item_change_callback(self._handle_active_work_item_changed)
        set_active_work_item_token_usage_callback(self._handle_token_usage)
        enable_approval(tool_approval_enabled)

    def set_tool_approval_enabled(self, enabled: bool) -> None:
        """Enable or disable tool approval for future tool calls."""
        from src.ariadne.tools.tool_wrapper import enable_approval

        enable_approval(enabled)
        self.reset_session_approval()

    def reset_session_approval(self) -> None:
        """Reset session-wide approval state."""
        if self._reset_session_approval:
            self._reset_session_approval()
            return

        from src.ariadne.tools.tool_wrapper import reset_session_approval

        reset_session_approval()

    def cancel_active_run(self) -> bool:
        """Request cancellation for the active agent run."""
        from src.ariadne.runtime import run_manager

        return run_manager.request_cancel() is not None

    def _handle_tool_notify(
        self,
        tool_name: str,
        status: str,
        args: dict,
        result: str,
    ) -> None:
        """Translate raw tool-wrapper notifications into application events."""
        normalized_status: Literal["start", "success", "error", "cancelled"]
        if status in {"start", "success", "error", "cancelled"}:
            normalized_status = status
        else:
            normalized_status = "error"

        event = ToolEvent(
            name=tool_name,
            status=normalized_status,
            args=args,
            result=result,
        )
        if self._tool_event_callback:
            self._tool_event_callback(event)

        if self.has_active_work_item() and normalized_status in {
            "success",
            "error",
            "cancelled",
        }:
            self._emit_active_work_item()

    def _handle_active_work_item_changed(self, work_item_id: str | None) -> None:
        """Translate active work item id changes into display-safe info."""
        self.set_active_work_item_id(work_item_id)
        self._emit_active_work_item()

    def _handle_token_usage(self, usage: dict[str, int]) -> None:
        """Translate raw token usage dictionaries into application events."""
        token_usage = TokenUsage.from_dict(usage)
        if token_usage and self._token_usage_callback:
            self._token_usage_callback(token_usage)

    def _emit_active_work_item(self) -> None:
        if self._active_work_item_callback:
            self._active_work_item_callback(self.get_active_work_item_info())

    async def handle_user_message(self, message: str, response: Any) -> None:
        """Send a user message to the active agent."""
        if self._current_agent:
            from .agent_runner import run_agent

            await run_agent(
                message,
                self._current_agent,
                emit=lambda event: self._apply_run_event(response, event),
                is_cancelled=lambda: bool(getattr(response, "is_cancelled", False)),
            )
        elif self._init_error:
            response.error(self._init_error)
        else:
            response.error("No agent selected. Use /agent to select one.")

    def _apply_run_event(self, response: Any, event: RunEvent) -> None:
        """Render a structured run event into the current UI response."""
        if event.type == "run_started":
            if hasattr(response, "activity"):
                response.activity("Run", event.detail)
        elif event.type == "run_finished":
            if hasattr(response, "activity"):
                response.activity("Run", event.detail)
        elif event.type == "thinking":
            if hasattr(response, "activity"):
                response.activity("Model", event.detail or event.message)
            response.thinking(event.detail or event.message)
        elif event.type == "response_start":
            response.start_response()
        elif event.type == "response_delta":
            response.append_response(event.message)
        elif event.type == "tool_start":
            if hasattr(response, "activity"):
                response.activity(f"Tool: {event.tool_name}", event.detail)
            response.tool(event.tool_name, event.detail)
        elif event.type == "token_usage" and event.usage:
            response.set_token_usage(event.usage.to_dict())
        elif event.type == "complete":
            response.complete(event.message)
        elif event.type == "error":
            response.error(event.message)
        elif event.type == "cancelled":
            if hasattr(response, "activity") and event.detail:
                response.activity("Run", event.detail)
            if not getattr(response, "is_cancelled", False):
                response.cancel()

    def load_initial_agent(self) -> CommandResult:
        """Initialize the default agent and auto-load history when available."""
        agents = self.list_agents()
        if not agents:
            return CommandResult("No agent initialized. Use `/agent` to select one.")

        result = self.switch_agent(agents[0].name)
        if result.is_error:
            return result

        if self._current_agent_name:
            try:
                load_history(self._current_agent, self._current_agent_name)
                logger.info("Auto-loaded history for %s", self._current_agent_name)
            except HistoryNotFoundError:
                pass
            except HistoryError as e:
                logger.warning(
                    "Failed to auto-load history for %s: %s",
                    self._current_agent_name,
                    e,
                )
        return result

    def save_chat_history(self) -> CommandResult:
        """Save chat history for the active agent."""
        if not self._current_agent or not self._current_agent_name:
            return CommandResult("No agent selected. Use /agent first.", is_error=True)

        if save_history(self._current_agent, self._current_agent_name):
            return CommandResult(f"Chat history saved for **{self._current_agent_name}**")
        return CommandResult("Failed to save chat history", is_error=True)

    def load_chat_history(self) -> CommandResult:
        """Load chat history for the active agent."""
        if not self._current_agent or not self._current_agent_name:
            return CommandResult("No agent selected. Use /agent first.", is_error=True)

        try:
            if load_history(self._current_agent, self._current_agent_name):
                summary = get_history_summary(self._current_agent_name)
                count = summary.get("message_count", 0) if summary else 0
                return CommandResult(
                    f"Loaded {count} messages for **{self._current_agent_name}**"
                )
            return CommandResult("Current agent does not support history loading.", is_error=True)
        except HistoryNotFoundError:
            return CommandResult(
                f"No saved history found for **{self._current_agent_name}**"
            )
        except HistoryFormatError as e:
            return CommandResult(
                f"Failed to load history: Invalid format ({str(e)})",
                is_error=True,
            )
        except HistoryError as e:
            return CommandResult(f"Failed to load history: {str(e)}", is_error=True)
        except Exception as e:
            return CommandResult(f"An unexpected error occurred: {str(e)}", is_error=True)

    def get_history_status(self) -> CommandResult:
        """Return history status for all agents."""
        lines = ["**Chat History Status:**\n"]
        for agent in self.list_agents():
            summary = get_history_summary(agent.name)
            active = " (active)" if agent.name == self._current_agent_name else ""
            if summary:
                count = summary.get("message_count", 0)
                lines.append(f"- `{agent.name}`{active}: {count} messages saved")
            else:
                lines.append(f"- `{agent.name}`{active}: No saved history")

        lines.append("\nUse `/save` to save or `/load` to restore history.")
        return CommandResult("\n".join(lines))

    def clear_chat_history(self) -> CommandResult:
        """Clear saved and in-memory history for the active agent."""
        if not self._current_agent_name:
            return CommandResult("No agent selected. Use /agent first.", is_error=True)

        if not clear_history(self._current_agent_name):
            return CommandResult("Failed to clear chat history", is_error=True)

        if self._current_agent and hasattr(self._current_agent, "clear_history"):
            self._current_agent.clear_history()

        return CommandResult(f"History cleared for **{self._current_agent_name}**")

    def get_secret_completions(self, context: str = "") -> list[str]:
        """Return vault key completions for the UI."""
        from src.ariadne.config.vault import Vault

        keys = Vault.list_managed_keys()
        parts = context.split()
        if len(parts) >= 1 and context.endswith(" "):
            return ["delete"]
        return keys

    def manage_secret(self, args: str = "") -> CommandResult:
        """Manage API keys in the secure vault."""
        from src.ariadne.config.vault import Vault

        parts = args.split(maxsplit=1)
        key_name = parts[0].upper() if parts else ""
        value = parts[1] if len(parts) > 1 else ""
        managed_keys = Vault.list_managed_keys()

        if not key_name:
            lines = ["**Secret Vault Status:**\n"]
            for key in managed_keys:
                secret = Vault.get_secret(key)
                if secret:
                    masked = secret[:4] + "..." + secret[-4:] if len(secret) > 8 else "****"
                    lines.append(f"- `{key}`: {masked}")
                else:
                    lines.append(f"- `{key}`: *not set*")
            lines.append("\n**Usage:**")
            lines.append("- `/secret KEY VALUE` - Set a secret")
            lines.append("- `/secret KEY delete` - Remove a secret")
            return CommandResult("\n".join(lines))

        if key_name not in managed_keys:
            available = ", ".join(f"`{k}`" for k in managed_keys)
            return CommandResult(
                f"Unknown key `{key_name}`. Available: {available}",
                is_error=True,
            )

        if not value:
            secret = Vault.get_secret(key_name)
            if secret:
                masked = secret[:4] + "..." + secret[-4:] if len(secret) > 8 else "****"
                return CommandResult(f"`{key_name}` is set: {masked}")
            return CommandResult(
                f"`{key_name}` is not set.\n\nUse `/secret {key_name} YOUR_API_KEY` to set it."
            )

        if value.lower() == "delete":
            try:
                Vault.delete_secret(key_name)
                self.clear_agent_cache()
                return CommandResult(
                    f"Deleted `{key_name}` from vault.\n\n"
                    f"Use `/agent` to re-initialize an agent."
                )
            except Exception as e:
                return CommandResult(f"Failed to delete secret: {e}", is_error=True)

        try:
            Vault.set_secret(key_name, value)
            self.clear_agent_cache()
            return CommandResult(
                f"Saved `{key_name}` to secure vault.\n\n"
                f"Use `/agent` to re-initialize an agent with the new key."
            )
        except Exception as e:
            return CommandResult(f"Failed to save secret: {e}", is_error=True)

    def set_active_work_item_id(self, work_item_id: str | None) -> None:
        """Track the current active work item id."""
        self._active_work_item_id = work_item_id

    def has_active_work_item(self) -> bool:
        """Return True when an active work item id is set."""
        return bool(self._active_work_item_id)

    def get_active_work_item_info(self) -> WorkItemInfo | None:
        """Load display-safe active work item details."""
        work_item_id = self._active_work_item_id
        if not work_item_id:
            return None

        try:
            from src.ariadne.infrastructure.container import DependencyRegistry

            work_item = DependencyRegistry.get_work_item_tools().system.get_work_item(work_item_id)
            return WorkItemInfo(work_item.id, work_item.title, work_item.status)
        except Exception as e:
            logger.debug("Failed to load active work item #%s: %s", work_item_id, e)
            return WorkItemInfo(work_item_id, "Unable to load", "Unknown")
