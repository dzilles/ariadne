import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.ui.message_display import ActivityAnimation, DisplayMode
from src.ariadne.ui.message import BotResponse, ResponseState


def test_cancelled_response_is_visible_without_text():
    response = BotResponse()

    response.cancel()

    assert response.state == ResponseState.CANCELLED
    assert response.has_content()


def test_token_only_response_is_visible():
    response = BotResponse()

    response.set_token_usage(
        {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
    )

    assert response.has_content()


def test_activity_line_is_visible():
    response = BotResponse()

    response.activity("Tool: list_files", ".")

    assert response.has_content()
    assert response.tool_results[0].label == "Tool: list_files"
    assert response.tool_results[0].detail == "."


def test_transient_status_is_visible_while_active():
    response = BotResponse()

    response.thinking(animation=ActivityAnimation.WAVE)

    assert response.has_content()
    assert response.status.label == "Thinking"
    assert response.status.detail == ""
    assert response.status.mode == DisplayMode.TRANSIENT
    assert response.status.animation == ActivityAnimation.WAVE

    response.clear_status()

    assert response.status is None
    assert not response.has_content()


def test_thinking_status_can_show_provider_summary():
    response = BotResponse()

    response.thinking("Checking the repository state.")

    assert response.status.label == "Thinking"
    assert response.status.detail == "Checking the repository state."


def test_activity_can_be_verbose_only():
    response = BotResponse()

    response.activity("Tool: demo", "ok", mode=DisplayMode.VERBOSE)

    assert response.tool_results[0].mode == DisplayMode.VERBOSE
