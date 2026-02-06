"""Utility to wrap tools with error handling and approval for graceful LLM recovery."""

import functools
import logging
import asyncio
import threading
import queue
from typing import Callable, Any, Optional

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


def _request_approval_sync(tool_name: str, args: dict) -> bool:
    """Request approval synchronously using a thread-safe queue mechanism."""
    global _auto_approve_session

    if not _approval_enabled or _auto_approve_session:
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

    Preserves function metadata (name, docstring, annotations) for LangChain/LangGraph.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        tool_name = func.__name__

        # Check if approval is needed
        if _approval_callback and _approval_enabled and not _auto_approve_session:
            if not _request_approval_sync(tool_name, kwargs):
                result = f"[Tool Cancelled: {tool_name}] User rejected the operation."
                _notify_tool(tool_name, "error", kwargs, result)
                return result

        # Notify tool start
        _notify_tool(tool_name, "start", kwargs, "")

        try:
            result = func(*args, **kwargs)
            # Check if result indicates an error
            result_str = str(result)
            if result_str.startswith("[Tool Error:"):
                _notify_tool(tool_name, "error", kwargs, result_str)
            else:
                _notify_tool(tool_name, "success", kwargs, result_str)
            return result
        except Exception as e:
            error_msg = f"[Tool Error: {tool_name}] {type(e).__name__}: {str(e)}"
            logger.error(error_msg)
            _notify_tool(tool_name, "error", kwargs, error_msg)
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
