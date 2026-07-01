import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.application.agent_runner import (
    _complete_from_history,
    _format_duration,
    _set_available_usage,
)


class FakeChunk:
    usage_metadata = {
        "input_tokens": 8,
        "output_tokens": 3,
        "total_tokens": 11,
    }


def test_set_available_usage_copies_streamed_usage_metadata(monkeypatch):
    notified = []
    monkeypatch.setattr(
        "src.ariadne.application.agent_runner.notify_active_work_item_token_usage",
        notified.append,
    )
    events = []

    _set_available_usage(events.append, [FakeChunk()])

    assert events[0].type == "token_usage"
    assert events[0].usage.to_dict() == {
        "input_tokens": 8,
        "output_tokens": 3,
        "total_tokens": 11,
    }
    assert notified == [events[0].usage.to_dict()]


class FakeMessage:
    content = "Done"


def test_complete_from_history_emits_completion_event():
    events = []

    _complete_from_history(events.append, [FakeMessage()])

    assert events[0].type == "complete"
    assert events[0].message == "Done"


def test_format_duration_for_run_lifecycle_events():
    assert _format_duration(1.234) == "1.2s"
    assert _format_duration(12.34) == "12s"
