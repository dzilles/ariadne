import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.ui.conversation_archive import (
    conversation_to_text,
    conversation_to_records,
    last_bot_response_text,
    read_conversation_archive,
    write_conversation_archive,
)
from src.ariadne.ui.message_display import DisplayMode
from src.ariadne.ui.message import BotResponse, UserMessage


def test_conversation_to_records_serializes_ui_messages():
    response = BotResponse()
    response.complete("Done")
    response.set_token_usage({"input_tokens": 2, "output_tokens": 3, "total_tokens": 5})
    response.add_error("Tool Failed", "No access")

    records = conversation_to_records([UserMessage("Hello"), response])

    assert records == [
        {"role": "user", "content": "Hello"},
        {
            "role": "assistant",
            "response": "Done",
            "token_usage": {
                "input_tokens": 2,
                "output_tokens": 3,
                "total_tokens": 5,
            },
            "errors": [{"label": "Tool Failed", "detail": "No access"}],
        },
    ]


def test_conversation_archive_round_trips_json_file(tmp_path):
    archive = tmp_path / "conversation.json"

    write_conversation_archive([UserMessage("Hello")], str(archive))

    assert json.loads(archive.read_text()) == [
        {"role": "user", "content": "Hello"}
    ]
    assert read_conversation_archive(str(archive)) == [
        {"role": "user", "content": "Hello"}
    ]


def test_conversation_to_text_includes_debug_rows_and_tokens():
    response = BotResponse()
    response.activity("Tool: read_file", "src/app.py", mode=DisplayMode.PERSISTENT)
    response.complete("Done")
    response.set_token_usage({"input_tokens": 2, "output_tokens": 3, "total_tokens": 5})

    text = conversation_to_text([UserMessage("Hello"), response])

    assert "User:\nHello" in text
    assert "Assistant:" in text
    assert "Event: Tool: read_file: src/app.py" in text
    assert "Done" in text
    assert "Tokens: in 2 | out 3 | total 5" in text


def test_conversation_to_text_includes_active_status():
    response = BotResponse()
    response.thinking("Processing tool result...")

    text = conversation_to_text([response])

    assert "Active: Thinking: Processing tool result..." in text


def test_last_bot_response_text_uses_latest_copyable_response():
    first = BotResponse().complete("First")
    second = BotResponse().activity("Tool: read_file", "src/app.py")

    assert "Tool: read_file" in last_bot_response_text([first, UserMessage("x"), second])
