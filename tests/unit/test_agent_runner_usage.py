import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.application.agent_runner import (
    _complete_from_history,
    _format_duration,
    _set_available_usage,
    run_agent,
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


class FakeSyncAgent:
    def __init__(self, result="Echo: hello", on_chat=None):
        self.chat_history = []
        self.result = result
        self.on_chat = on_chat

    def chat(self, message):
        if self.on_chat:
            self.on_chat(message)
        return self.result


def test_run_agent_emits_lifecycle_events_for_sync_agent():
    events = []

    asyncio.run(
        run_agent(
            "hello",
            FakeSyncAgent(result="Echo: hello"),
            emit=events.append,
            is_cancelled=lambda: False,
        )
    )

    event_types = [event.type for event in events]
    assert event_types == ["run_started", "thinking", "complete", "run_finished"]
    assert events[2].message == "Echo: hello"
    assert events[3].duration_seconds is not None


def test_run_agent_emits_cancelled_for_sync_agent():
    events = []
    cancelled = False

    def cancel_after_chat(_message):
        nonlocal cancelled
        cancelled = True

    asyncio.run(
        run_agent(
            "hello",
            FakeSyncAgent(on_chat=cancel_after_chat),
            emit=events.append,
            is_cancelled=lambda: cancelled,
        )
    )

    event_types = [event.type for event in events]
    assert event_types == ["run_started", "thinking", "cancelled"]
    assert events[2].duration_seconds is not None
