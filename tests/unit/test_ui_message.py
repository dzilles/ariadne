import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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

    response.activity("Model", "Model request started...")

    assert response.has_content()
    assert response.tool_results[0].label == "Model"
    assert response.tool_results[0].detail == "Model request started..."
