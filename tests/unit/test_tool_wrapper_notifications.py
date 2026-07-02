import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.tools import tool_wrapper


class ImmediateLoop:
    def call_soon_threadsafe(self, callback):
        callback()


def test_notify_tool_emits_structured_notification(monkeypatch):
    notifications = []
    monkeypatch.setattr(tool_wrapper, "_tool_notify_callback", notifications.append)
    monkeypatch.setattr(tool_wrapper, "_event_loop", ImmediateLoop())

    tool_wrapper._notify_tool("read_file", "success", {"path": "a.txt"}, "ok")

    assert notifications[0].name == "read_file"
    assert notifications[0].status == "success"
    assert notifications[0].args == {"path": "a.txt"}
    assert notifications[0].result == "ok"
