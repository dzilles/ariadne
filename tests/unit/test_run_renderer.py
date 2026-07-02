import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.application.ui_contract import RunEvent
from src.ariadne.ui.message import BotResponse
from src.ariadne.ui.message_display import ActivityAnimation
from src.ariadne.ui.run_renderer import render_run_event


def test_thinking_event_sets_transient_status():
    response = BotResponse()

    render_run_event(
        response,
        RunEvent("thinking", detail="Model request started..."),
    )

    assert response.status.label == "Thinking"
    assert response.status.detail == "Model request started..."
    assert response.status.animation == ActivityAnimation.WAVE
    assert response.tool_results == []


def test_run_finished_event_is_hidden():
    response = BotResponse()

    render_run_event(
        response,
        RunEvent("run_finished", detail="Finished in 1.2s", duration_seconds=1.2),
    )

    assert not response.has_content()


def test_tool_start_event_adds_persistent_activity_and_active_status():
    response = BotResponse()

    render_run_event(
        response,
        RunEvent(
            "tool_start",
            tool_name="read_file",
            detail="Running...",
            args={"file_path": "src/app.py"},
        ),
    )

    assert response.tool_results[0].label == "Tool: read_file"
    assert response.tool_results[0].detail == "src/app.py"
    assert response.status.label == "Tool: read_file"
    assert response.status.detail == "src/app.py"
    assert response.status.animation == ActivityAnimation.WAVE
