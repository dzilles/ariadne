"""Render application run events into chat UI responses."""

from typing import Any

from src.ariadne.application.ui_contract import RunEvent
from src.ariadne.ui.message_display import (
    DisplayMode,
    format_tool_call_detail,
    run_event_rule,
)


def render_run_event(response: Any, event: RunEvent) -> None:
    """Apply a structured run event to a chat response."""
    rule = run_event_rule(event.type)
    if rule.mode == DisplayMode.HIDDEN and event.type in {
        "run_started",
        "run_finished",
    }:
        return

    if event.type == "run_started":
        response.activity(
            "Run",
            event.detail,
            mode=rule.mode,
            animation=rule.animation,
        )
    elif event.type == "run_finished":
        response.activity(
            "Run",
            event.detail,
            mode=rule.mode,
            animation=rule.animation,
        )
    elif event.type == "thinking":
        response.thinking(animation=rule.animation)
    elif event.type == "response_start":
        response.start_response()
    elif event.type == "response_delta":
        response.append_response(event.message)
    elif event.type == "tool_start":
        detail = format_tool_call_detail(event.tool_name, event.args)
        response.activity(
            f"Tool: {event.tool_name}",
            detail,
            mode=rule.mode,
            animation=rule.animation,
        )
        response.tool(event.tool_name, detail, animation=rule.animation)
    elif event.type == "token_usage" and event.usage:
        response.set_token_usage(event.usage.to_dict())
    elif event.type == "complete":
        response.complete(event.message)
    elif event.type == "error":
        response.error(event.message)
    elif event.type == "cancelled":
        if event.detail:
            response.activity(
                "Run",
                event.detail,
                mode=rule.mode,
                animation=rule.animation,
            )
        if not getattr(response, "is_cancelled", False):
            response.cancel()
    elif event.type == "queued":
        response.info(event.detail or event.message)
