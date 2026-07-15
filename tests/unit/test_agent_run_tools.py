import json

from src.ariadne.tools.agent_run_tools import AgentRunTools


def _payload(result: str) -> dict:
    assert result.startswith("[AGENT_RUN_COMPLETE]\n")
    return json.loads(result.split("\n", 1)[1])


def test_finish_agent_run_returns_success_payload():
    tools = AgentRunTools()

    result = tools.finish_agent_run(
        "success",
        "Created requirements document.",
        details="Covered persistence and context deletion.",
        decisions=["Use structured context object."],
        blockers=[],
        artifacts=[
            {
                "title": "REQ-1",
                "url": "docs/requirements/REQ-1.md",
                "type": "requirement",
                "stable_id": "REQ-1",
                "metadata": {"phase": "analysis"},
            }
        ],
    )
    payload = _payload(result)

    assert payload["schema_version"] == 1
    assert payload["status"] == "SUCCESS"
    assert payload["summary"] == "Created requirements document."
    assert payload["details"] == "Covered persistence and context deletion."
    assert payload["decisions"] == ["Use structured context object."]
    assert payload["blockers"] == []
    assert payload["artifacts"] == [
        {
            "title": "REQ-1",
            "url": "docs/requirements/REQ-1.md",
            "type": "requirement",
            "stable_id": "REQ-1",
            "metadata": {"phase": "analysis"},
        }
    ]


def test_return_to_orchestrator_records_typed_completion():
    tools = AgentRunTools()

    result = tools.return_to_orchestrator("SUCCESS", "Returned typed result.")

    assert _payload(result)["summary"] == "Returned typed result."
    assert tools.terminal_call_count == 1
    assert tools.completion is not None
    assert tools.completion.summary == "Returned typed result."


def test_terminal_completion_can_only_be_recorded_once():
    tools = AgentRunTools()

    tools.return_to_orchestrator("SUCCESS", "First result.")
    result = tools.finish_agent_run("SUCCESS", "Second result.")

    assert (
        result == "Error: return_to_orchestrator may only be called once per agent run."
    )
    assert tools.terminal_call_count == 2
    assert tools.completion is not None
    assert tools.completion.summary == "First result."


def test_finish_agent_run_returns_failed_payload():
    tools = AgentRunTools()

    result = tools.finish_agent_run("FAILED", "Missing acceptance criteria.")

    assert _payload(result)["status"] == "FAILED"
    assert _payload(result)["summary"] == "Missing acceptance criteria."


def test_finish_agent_run_rejects_invalid_status():
    tools = AgentRunTools()

    result = tools.finish_agent_run("BLOCKED", "Need input.")

    assert result == "Error: status must be SUCCESS or FAILED."


def test_finish_agent_run_requires_summary():
    tools = AgentRunTools()

    result = tools.finish_agent_run("SUCCESS", "  ")

    assert result == "Error: summary cannot be empty."
