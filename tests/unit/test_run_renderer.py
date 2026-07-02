import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.application.ui_contract import RunEvent
from src.ariadne.ui.message import BotResponse
from src.ariadne.ui.run_renderer import render_run_event


def test_run_event_adds_visible_activity_line():
    response = BotResponse()

    render_run_event(
        response,
        RunEvent("thinking", detail="Model request started..."),
    )

    assert response.tool_results[0].label == "Model"
    assert response.tool_results[0].detail == "Model request started..."
    assert response.status.label == "Thinking"


def test_run_finished_event_adds_visible_activity_line():
    response = BotResponse()

    render_run_event(
        response,
        RunEvent("run_finished", detail="Finished in 1.2s", duration_seconds=1.2),
    )

    assert response.tool_results[0].label == "Run"
    assert response.tool_results[0].detail == "Finished in 1.2s"
