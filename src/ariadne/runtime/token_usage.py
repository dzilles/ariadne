"""Token usage extraction and active work item reporting."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_active_work_item_token_usage_callback: Optional[Callable[[dict[str, int]], None]] = None


def set_active_work_item_token_usage_callback(
    callback: Optional[Callable[[dict[str, int]], None]]
) -> None:
    """Register a callback for token usage while a work item is active."""
    global _active_work_item_token_usage_callback
    _active_work_item_token_usage_callback = callback


def notify_active_work_item_token_usage(usage: dict[str, int] | None) -> None:
    """Notify listeners about token usage for the active work item."""
    if not usage or not _active_work_item_token_usage_callback:
        return
    try:
        _active_work_item_token_usage_callback(usage)
    except Exception as e:
        logger.debug("Active work item token usage callback failed: %s", e)


def _coerce_token_count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _add_usage(total: dict[str, int], usage: dict[str, Any]) -> None:
    input_tokens = (
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or usage.get("input_token_count")
        or usage.get("prompt_token_count")
    )
    output_tokens = (
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or usage.get("output_token_count")
        or usage.get("candidates_token_count")
    )
    total_tokens = (
        usage.get("total_tokens")
        or usage.get("total_token_count")
    )

    total["input_tokens"] += _coerce_token_count(input_tokens)
    total["output_tokens"] += _coerce_token_count(output_tokens)
    total["total_tokens"] += _coerce_token_count(total_tokens)


def extract_token_usage(messages: list[Any]) -> dict[str, int] | None:
    """Extract aggregate token usage from LangChain messages."""
    total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    for message in messages:
        usage_metadata = getattr(message, "usage_metadata", None)
        if isinstance(usage_metadata, dict):
            _add_usage(total, usage_metadata)

        response_metadata = getattr(message, "response_metadata", None)
        if isinstance(response_metadata, dict):
            token_usage = response_metadata.get("token_usage")
            if isinstance(token_usage, dict):
                _add_usage(total, token_usage)
            usage = response_metadata.get("usage")
            if isinstance(usage, dict):
                _add_usage(total, usage)

    if not any(total.values()):
        return None

    if not total["total_tokens"]:
        total["total_tokens"] = total["input_tokens"] + total["output_tokens"]
    return total
