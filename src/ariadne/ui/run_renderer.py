"""Render application run events into chat UI responses."""

from typing import Any

from src.ariadne.application.ui_contract import RunEvent


def render_run_event(response: Any, event: RunEvent) -> None:
    """Apply a structured run event to a chat response."""
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
