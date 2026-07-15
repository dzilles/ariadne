from src.ariadne.application.delegation import DelegationService
from src.ariadne.work_items.models import AgentCompletion, AgentRunStatus


class FakeWorkItemTools:
    def __init__(self):
        self.commit_hashes = []
        self.links = []
        self.shared_context = []
        self.status_updates = []
        self.comments = []

    def add_commit_hash(self, work_item_id, commit_hash):
        self.commit_hashes.append((work_item_id, commit_hash))
        return "ok"

    def add_link(
        self,
        work_item_id,
        title,
        url,
        comment=None,
        artifact_type="link",
        agent_run_id=None,
        metadata=None,
    ):
        self.links.append(
            (work_item_id, title, url, artifact_type, agent_run_id, metadata or {})
        )
        return "ok"

    def append_shared_context(
        self,
        work_item_id,
        author,
        context,
        agent_run_id=None,
        metadata=None,
    ):
        self.shared_context.append(
            (work_item_id, author, context, agent_run_id, metadata or {})
        )
        return "ok"

    def update_status(self, work_item_id, status):
        self.status_updates.append((work_item_id, status))
        return "ok"

    def post_comment(self, work_item_id, comment):
        self.comments.append((work_item_id, comment))
        return "ok"


def _service(tools=None):
    return DelegationService(
        tools or FakeWorkItemTools(),
        agent_factories={},
        project_path=".",
    )


def test_check_clean_git_status_blocks_dirty_worktree(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        service,
        "_run_git",
        lambda args: {"returncode": 0, "stdout": " M src/app.py", "stderr": ""},
    )

    result = service._check_clean_git_status()

    assert result.startswith("BLOCK: Cannot delegate")
    assert "M src/app.py" in result


def test_check_clean_git_status_allows_clean_worktree(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        service,
        "_run_git",
        lambda args: {"returncode": 0, "stdout": "", "stderr": ""},
    )

    assert service._check_clean_git_status() == ""


def test_format_handoff_context_uses_completion_and_evidence():
    service = _service()
    completion = {
        "status": "SUCCESS",
        "summary": "Created requirement.",
        "details": "Added acceptance criteria.",
        "decisions": ["Use structured handoff."],
        "blockers": [],
        "artifacts": [
            {"title": "REQ-1", "url": "docs/REQ-1.md", "type": "requirement"}
        ],
    }
    evidence = {
        "branch": "main",
        "latest_commit": "abc123",
        "status_short": "Clean",
        "changed_files": ["docs/REQ-1.md"],
        "diff_stat": "1 file changed",
    }

    context = service._format_handoff_context(
        "Requirements",
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


def test_apply_agent_run_to_work_item_records_new_commit_and_artifacts():
    tools = FakeWorkItemTools()
    service = _service(tools)
    completion = AgentCompletion.model_validate(
        {
            "status": "SUCCESS",
            "summary": "Created artifacts.",
            "artifacts": [
                {
                    "title": "Spec",
                    "url": "docs/spec.md",
                    "type": "requirement",
                    "metadata": {"phase": "analysis"},
                },
                {"title": "Design", "url": "docs/design.md", "type": "design"},
            ],
        }
    )
    evidence = {"starting_commit": "abc123", "latest_commit": "def456"}

    service._apply_agent_run_to_work_item(
        "7",
        completion,
        evidence,
        agent_run_id="99",
    )

    assert tools.commit_hashes == [("7", "def456")]
    assert tools.links == [
        ("7", "Spec", "docs/spec.md", "requirement", "99", {"phase": "analysis"}),
        ("7", "Design", "docs/design.md", "design", "99", {}),
    ]


def test_apply_agent_run_to_work_item_ignores_unchanged_commit():
    tools = FakeWorkItemTools()
    service = _service(tools)
    completion = AgentCompletion(status="SUCCESS", summary="Done")

    service._apply_agent_run_to_work_item(
        "7",
        completion,
        {"starting_commit": "abc123", "latest_commit": "abc123"},
        agent_run_id="99",
    )

    assert tools.commit_hashes == []
    assert tools.links == []


def test_apply_agent_run_to_work_item_blocks_and_comments_on_failed_run():
    tools = FakeWorkItemTools()
    service = _service(tools)
    completion = AgentCompletion(
        status="FAILED",
        summary="Could not write requirement.",
        details="Template was missing.",
        blockers=["Need requirements template."],
        artifacts=[{"title": "Spec", "url": "docs/spec.md"}],
    )

    service._apply_agent_run_to_work_item(
        "7",
        completion,
        {"starting_commit": "abc123", "latest_commit": "def456"},
        agent_run_id="99",
    )

    assert tools.status_updates == [("7", "Blocked")]
    assert len(tools.comments) == 1
    assert "Summary: Could not write requirement." in tools.comments[0][1]
    assert "Template was missing." in tools.comments[0][1]
    assert "- Need requirements template." in tools.comments[0][1]
    assert tools.commit_hashes == []
    assert tools.links == []


def test_append_agent_handoff_context_links_context_to_agent_run():
    tools = FakeWorkItemTools()
    service = _service(tools)
    completion = AgentCompletion(
        status="SUCCESS",
        summary="Finished design.",
        artifacts=[{"title": "Design", "url": "docs/design.md"}],
    )
    evidence = {
        "latest_commit": "abc123",
        "changed_files": ["docs/design.md"],
    }

    service._append_agent_handoff_context(
        "7",
        "Architect",
        completion,
        evidence,
        agent_run_id="99",
        run_status=AgentRunStatus.SUCCESS,
    )

    assert len(tools.shared_context) == 1
    work_item_id, author, context, agent_run_id, metadata = tools.shared_context[0]
    assert work_item_id == "7"
    assert author == "Architect"
    assert "Summary: Finished design." in context
    assert agent_run_id == "99"
    assert metadata == {
        "status": "SUCCESS",
        "latest_commit": "abc123",
        "changed_files": ["docs/design.md"],
        "artifact_count": 1,
    }
