import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.application.ui_contract import ToolEvent
from src.ariadne.ui.launcher import AriadneTUI
from src.ariadne.ui.message import BotResponse


class FakeUI:
    def __init__(self, response):
        self.conversation = type("Conversation", (), {"messages": [response]})()


def test_late_tool_event_does_not_reopen_completed_response():
    response = BotResponse()
    response.complete("Done")
    tui = AriadneTUI.__new__(AriadneTUI)
    tui.ui = FakeUI(response)
    tui._active_tool_response = None

    tui._on_tool_event(
        ToolEvent("list_files", "success", {"directory": "."}, "file.txt")
    )

    assert response.response == "Done"
    assert response.status is None
    assert response.tool_results == []
