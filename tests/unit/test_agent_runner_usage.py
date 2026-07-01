import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.application.agent_runner import _set_available_usage


class FakeChunk:
    usage_metadata = {
        "input_tokens": 8,
        "output_tokens": 3,
        "total_tokens": 11,
    }


class FakeResponse:
    def __init__(self):
        self.token_usage = None

    def set_token_usage(self, usage):
        self.token_usage = usage


def test_set_available_usage_copies_streamed_usage_metadata(monkeypatch):
    notified = []
    monkeypatch.setattr(
        "src.ariadne.application.agent_runner.notify_active_work_item_token_usage",
        notified.append,
    )
    response = FakeResponse()

    _set_available_usage(response, [FakeChunk()])

    assert response.token_usage == {
        "input_tokens": 8,
        "output_tokens": 3,
        "total_tokens": 11,
    }
    assert notified == [response.token_usage]
