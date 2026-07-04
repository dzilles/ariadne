import json

from src.ariadne.agents.orchestrator_agent import OrchestratorAgent


class FakeWorkItemTools:
    def __init__(self):
        self.commit_hashes = []
        self.links = []

    def add_commit_hash(self, work_item_id, commit_hash):
        self.commit_hashes.append((work_item_id, commit_hash))
        return "ok"

    def add_link(self, work_item_id, title, url):
        self.links.append((work_item_id, title, url))
        return "ok"


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


def test_apply_agent_run_to_work_item_records_new_commit_and_artifacts():
    agent = OrchestratorAgent.__new__(OrchestratorAgent)
    tools = FakeWorkItemTools()
    agent.ticket_tools = tools
    completion = {
        "status": "SUCCESS",
        "artifacts": [
            {"title": "Spec", "url": "docs/spec.md"},
            {"name": "Design", "path": "docs/design.md"},
        ],
    }
    evidence = {
        "starting_commit": "abc123",
        "latest_commit": "def456",
    }

    agent._apply_agent_run_to_work_item("7", completion, evidence)

    assert tools.commit_hashes == [("7", "def456")]
    assert tools.links == [
        ("7", "Spec", "docs/spec.md"),
        ("7", "Design", "docs/design.md"),
    ]


def test_apply_agent_run_to_work_item_ignores_failed_or_unchanged_runs():
    agent = OrchestratorAgent.__new__(OrchestratorAgent)
    tools = FakeWorkItemTools()
    agent.ticket_tools = tools

    agent._apply_agent_run_to_work_item(
        "7",
        {"status": "FAILED", "artifacts": [{"title": "Spec", "url": "docs/spec.md"}]},
        {"starting_commit": "abc123", "latest_commit": "def456"},
    )
    agent._apply_agent_run_to_work_item(
        "7",
        {"status": "SUCCESS", "artifacts": []},
        {"starting_commit": "abc123", "latest_commit": "abc123"},
    )

    assert tools.commit_hashes == []
    assert tools.links == []
