import json

from src.ariadne.agents.orchestrator_agent import OrchestratorAgent


def test_check_clean_git_status_blocks_dirty_worktree(monkeypatch):
    agent = OrchestratorAgent.__new__(OrchestratorAgent)
    monkeypatch.setattr(
        agent,
        "_run_git",
        lambda args: {"returncode": 0, "stdout": " M src/app.py", "stderr": ""},
    )

    result = agent._check_clean_git_status()

    assert result.startswith("⛔ BLOCK: Cannot delegate")
    assert "M src/app.py" in result


def test_check_clean_git_status_allows_clean_worktree(monkeypatch):
    agent = OrchestratorAgent.__new__(OrchestratorAgent)
    monkeypatch.setattr(
        agent,
        "_run_git",
        lambda args: {"returncode": 0, "stdout": "", "stderr": ""},
    )

    assert agent._check_clean_git_status() == ""


def test_format_handoff_context_uses_completion_and_evidence():
    agent = OrchestratorAgent.__new__(OrchestratorAgent)
    completion = {
        "status": "SUCCESS",
        "summary": "Created requirement.",
        "details": "Added acceptance criteria.",
        "decisions": ["Use structured handoff."],
        "blockers": [],
        "artifacts": [{"title": "REQ-1", "url": "docs/REQ-1.md", "type": "requirement"}],
    }
    evidence = {
        "branch": "main",
        "latest_commit": "abc123",
        "status_short": "Clean",
        "changed_files": ["docs/REQ-1.md"],
        "diff_stat": "1 file changed",
    }

    context = agent._format_handoff_context(
        "Requirements",
        "",
        completion,
        evidence,
    )

    assert "Delegated agent: Requirements" in context
    assert "Status: SUCCESS" in context
    assert "Summary: Created requirement." in context
    assert "- Use structured handoff." in context
    assert "docs/REQ-1.md" in context
    assert "- Branch: main" in context
    assert "- Changed files: docs/REQ-1.md" in context


def test_parse_agent_completion_reads_marked_json():
    agent = OrchestratorAgent.__new__(OrchestratorAgent)
    payload = {"status": "SUCCESS", "summary": "Done"}
    response = "[AGENT_RUN_COMPLETE]\n" + json.dumps(payload)

    assert agent._parse_agent_completion(response) == payload
