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
            }
        ],
    )
    payload = _payload(result)

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
        }
    ]


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
