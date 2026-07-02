"""Utility to wrap tools with error handling and approval for graceful LLM recovery."""

import functools
import inspect
import logging
import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Any, Optional, Literal

from src.ariadne.runtime.context import get_active_work_item_id
from src.ariadne.runtime.run_manager import is_cancel_requested

logger = logging.getLogger(__name__)

ToolNotificationStatus = Literal["start", "success", "error", "cancelled"]


@dataclass(frozen=True)
class ToolNotification:
    """Structured notification emitted by wrapped tools."""

    name: str
    status: ToolNotificationStatus
    args: dict
    result: str = ""

# Global approval state
_approval_callback: Optional[Callable[[str, dict], Any]] = None
_tool_notify_callback: Optional[Callable[[ToolNotification], None]] = None
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_approval_enabled: bool = True
_auto_approve_session: bool = False
APPROVAL_TIMEOUT_SECONDS = 300
APPROVAL_POLL_INTERVAL_SECONDS = 0.1


def set_approval_callback(callback: Callable[[str, dict], Any], loop: asyncio.AbstractEventLoop = None) -> None:
    """Set the async approval callback.

    Args:
        callback: Async function that takes (tool_name, args) and returns
                  "yes", "no", or "session" (approve all for this session)
        loop: The event loop to use for scheduling the callback
    """
    global _approval_callback, _event_loop
    _approval_callback = callback
    _event_loop = loop


def set_tool_notify_callback(callback: Callable[[ToolNotification], None]) -> None:
    """Set callback to notify about tool execution.

    Args:
        callback: Function that takes a ToolNotification.
    """
    global _tool_notify_callback
    _tool_notify_callback = callback


def _notify_tool(
    tool_name: str,
    status: ToolNotificationStatus,
    args: dict,
    result: str = "",
) -> None:
    """Notify about tool execution via callback."""
    if _tool_notify_callback and _event_loop:
        notification = ToolNotification(tool_name, status, args, result)
        try:
            _event_loop.call_soon_threadsafe(
                lambda: _tool_notify_callback(notification)
            )
        except Exception as e:
            logger.debug(f"Tool notify error: {e}")


def _serialize_tool_args(args: tuple, kwargs: dict) -> dict:
    if kwargs:
        raw_args = kwargs
    else:
        raw_args = {"args": list(args)}

    serialized = {}
    for key, value in raw_args.items():
        try:
            json_value = _json_safe(value)
        except Exception:
            json_value = repr(value)
        serialized[str(key)] = json_value
    return serialized


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return repr(value)


def _is_tool_audited(tool_name: str, status: str) -> bool:
    from src.ariadne.config.settings import settings

    if not settings.tool_audit_enabled:
        return False

    configured_tools = set(settings.tool_audit_logged_tools)
    if "*" not in configured_tools and tool_name not in configured_tools:
        return False

    configured_statuses = set(settings.tool_audit_logged_statuses)
    return "*" in configured_statuses or status in configured_statuses


def _audit_tool_call(tool_name: str, status: str, args: dict, result: str = "") -> None:
    if not _is_tool_audited(tool_name, status):
        return

    work_item_id = get_active_work_item_id()
    if not work_item_id:
        return

    try:
        from src.ariadne.config.settings import settings
        from src.ariadne.infrastructure.container import DependencyRegistry

        max_chars = max(0, settings.tool_audit_result_max_chars)
        DependencyRegistry.get_sqlite_work_item_store().add_tool_log(
            work_item_id=work_item_id,
            tool_name=tool_name,
            status=status,
            args=args,
            result=str(result)[:max_chars],
        )
    except Exception as e:
        logger.debug("Tool audit logging failed for %s: %s", tool_name, e)


def enable_approval(enabled: bool = True) -> None:
    """Enable or disable tool approval prompts."""
    global _approval_enabled, _auto_approve_session
    _approval_enabled = enabled
    if not enabled:
        _auto_approve_session = False


def is_approval_enabled() -> bool:
    """Check if approval is currently enabled."""
    return _approval_enabled and not _auto_approve_session


def reset_session_approval() -> None:
    """Reset the session auto-approval (call when switching agents)."""
    global _auto_approve_session
    _auto_approve_session = False


def _request_approval_sync(
    tool_name: str,
    args: dict,
    ignore_session_approval: bool = False,
) -> bool:
    """Request approval synchronously using a thread-safe queue mechanism."""
    global _auto_approve_session

    if not _approval_enabled or (_auto_approve_session and not ignore_session_approval):
        return True

    if not _approval_callback:
        return True

    if not _event_loop:
        return True

    approval_future = None
    try:
        async def run_approval():
            result = _approval_callback(tool_name, args)
            if inspect.isawaitable(result):
                return await result
            return result

        approval_future = asyncio.run_coroutine_threadsafe(
            run_approval(),
            _event_loop,
        )
        result = _wait_for_approval_result(approval_future, tool_name)

        if result == "session":
            _auto_approve_session = True
            return True
        return result == "yes"
    except Exception as e:
        logger.error(f"Error requesting approval: {e}")
        if approval_future is not None:
            approval_future.cancel()
        return False


def _wait_for_approval_result(approval_future: Any, tool_name: str) -> str:
    """Wait for one approval future while honoring runtime cancellation."""
    deadline = time.monotonic() + APPROVAL_TIMEOUT_SECONDS
    while True:
        if is_cancel_requested():
            approval_future.cancel()
            return "no"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.error(
                "Tool approval timed out after %s seconds for %s",
                APPROVAL_TIMEOUT_SECONDS,
                tool_name,
            )
            approval_future.cancel()
            return "no"
        if approval_future.done():
            return approval_future.result()
        time.sleep(min(APPROVAL_POLL_INTERVAL_SECONDS, remaining))


def with_error_handling(func: Callable) -> Callable:
    """Decorator that catches exceptions and optionally requests approval.
    Implementation of ARCH-15. Fulfills REQ-15.

    Preserves function metadata (name, docstring, annotations) for LangChain/LangGraph.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        tool_name = func.__name__
        tool_args = _serialize_tool_args(args, kwargs)

        if is_cancel_requested():
            result = f"[Tool Cancelled: {tool_name}] Run cancellation requested by user."
            _notify_tool(tool_name, "cancelled", tool_args, result)
            _audit_tool_call(tool_name, "cancelled", tool_args, result)
            return result

        approval_required = (
            _approval_callback
            and _approval_enabled
            and (not _auto_approve_session or tool_name == "delegate_to_agent")
        )

        # Check if approval is needed
        if approval_required:
            if not _request_approval_sync(
                tool_name,
                tool_args,
                ignore_session_approval=(tool_name == "delegate_to_agent"),
            ):
                reason = (
                    "Run cancellation requested by user."
                    if is_cancel_requested()
                    else "User rejected the operation."
                )
                result = f"[Tool Cancelled: {tool_name}] {reason}"
                _notify_tool(tool_name, "cancelled", tool_args, result)
                _audit_tool_call(tool_name, "cancelled", tool_args, result)
                return result

        # Notify tool start
        _notify_tool(tool_name, "start", tool_args, "")

        try:
            if is_cancel_requested():
                result = f"[Tool Cancelled: {tool_name}] Run cancellation requested by user."
                _notify_tool(tool_name, "cancelled", tool_args, result)
                _audit_tool_call(tool_name, "cancelled", tool_args, result)
                return result
            result = func(*args, **kwargs)
            # Check if result indicates an error
            result_str = str(result)
            if result_str.startswith("[Tool Error:"):
                _notify_tool(tool_name, "error", tool_args, result_str)
                _audit_tool_call(tool_name, "error", tool_args, result_str)
            else:
                _notify_tool(tool_name, "success", tool_args, result_str)
                _audit_tool_call(tool_name, "success", tool_args, result_str)
            return result
        except Exception as e:
            error_msg = f"[Tool Error: {tool_name}] {type(e).__name__}: {str(e)}"
            logger.error(error_msg)
            _notify_tool(tool_name, "error", tool_args, error_msg)
            _audit_tool_call(tool_name, "error", tool_args, error_msg)
            return error_msg

    # Ensure all metadata is preserved for LangChain tool conversion
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    if hasattr(func, "__annotations__"):
        wrapper.__annotations__ = func.__annotations__

    return wrapper


def wrap_tools_with_error_handling(tools: list) -> list:
    """Wrap a list of tools/functions with error handling.

    Args:
        tools: List of tool functions or methods

    Returns:
        List of wrapped tools that return error strings instead of raising
    """
    wrapped = []
    for tool in tools:
        if callable(tool):
            wrapped.append(with_error_handling(tool))
        else:
            wrapped.append(tool)
    return wrapped
