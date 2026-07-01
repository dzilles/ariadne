"""Utility to wrap tools with error handling and approval for graceful LLM recovery."""

import functools
import logging
import asyncio
import queue
from typing import Callable, Any, Optional

from src.ariadne.config.settings import settings
from src.ariadne.runtime.context import get_active_work_item_id
from src.ariadne.runtime.run_manager import is_cancel_requested

logger = logging.getLogger(__name__)

# Global approval state
_approval_callback: Optional[Callable[[str, dict], Any]] = None
_tool_notify_callback: Optional[Callable[[str, str, dict, str], None]] = None  # (tool_name, status, args, result)
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_approval_enabled: bool = True
_auto_approve_session: bool = False


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


def set_tool_notify_callback(callback: Callable[[str, str, dict, str], None]) -> None:
    """Set callback to notify about tool execution.

    Args:
        callback: Function that takes (tool_name, status, args, result)
                  status is "start", "success", or "error"
    """
    global _tool_notify_callback
    _tool_notify_callback = callback


def _notify_tool(tool_name: str, status: str, args: dict, result: str = "") -> None:
    """Notify about tool execution via callback."""
    if _tool_notify_callback and _event_loop:
        try:
            _event_loop.call_soon_threadsafe(
                lambda: _tool_notify_callback(tool_name, status, args, result)
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

    try:
        # Use a queue to get the result from the async callback
        result_queue = queue.Queue()

        async def run_approval():
            try:
                result = await _approval_callback(tool_name, args)
                result_queue.put(result)
            except Exception as e:
                logger.error(f"Approval callback error: {e}")
                result_queue.put("yes")  # Default to approved on error

        # Schedule the coroutine on the event loop
        _event_loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(run_approval())
        )

        # Wait for the result (blocking)
        result = result_queue.get(timeout=300)  # 5 minute timeout

        if result == "session":
            _auto_approve_session = True
            return True
        return result == "yes"
    except Exception as e:
        logger.error(f"Error requesting approval: {e}")
        return True  # Default to approved on error


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
            _notify_tool(tool_name, "error", kwargs, result)
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
                kwargs,
                ignore_session_approval=(tool_name == "delegate_to_agent"),
            ):
                result = f"[Tool Cancelled: {tool_name}] User rejected the operation."
                _notify_tool(tool_name, "error", kwargs, result)
                _audit_tool_call(tool_name, "cancelled", tool_args, result)
                return result

        # Notify tool start
        _notify_tool(tool_name, "start", kwargs, "")

        try:
            if is_cancel_requested():
                result = f"[Tool Cancelled: {tool_name}] Run cancellation requested by user."
                _notify_tool(tool_name, "error", kwargs, result)
                _audit_tool_call(tool_name, "cancelled", tool_args, result)
                return result
            result = func(*args, **kwargs)
            # Check if result indicates an error
            result_str = str(result)
            if result_str.startswith("[Tool Error:"):
                _notify_tool(tool_name, "error", kwargs, result_str)
                _audit_tool_call(tool_name, "error", tool_args, result_str)
            else:
                _notify_tool(tool_name, "success", kwargs, result_str)
                _audit_tool_call(tool_name, "success", tool_args, result_str)
            return result
        except Exception as e:
            error_msg = f"[Tool Error: {tool_name}] {type(e).__name__}: {str(e)}"
            logger.error(error_msg)
            _notify_tool(tool_name, "error", kwargs, error_msg)
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
