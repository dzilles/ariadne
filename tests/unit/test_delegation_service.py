from types import SimpleNamespace

import pytest

from src.ariadne.application.delegation import (
    DelegationRejectedError,
    DelegationService,
)
from src.ariadne.policies.loader import get_policy
from src.ariadne.work_items.models import (
    AgentCompletion,
    AgentRunStatus,
    ArtifactLink,
    GateStatus,
    WorkItem,
    WorkItemStatus,
    WorkItemType,
)


class FakeStore:
    def __init__(self, work_item):
        self.work_item = work_item
        self.running_run = None
        self.blockers = []

    def get_work_item(self, work_item_id):
        assert str(work_item_id) == self.work_item.id
        return self.work_item

    def get_running_agent_run(self, work_item_id):
        return self.running_run

    def get_blockers(self, work_item_id):
        return self.blockers


class FakeWorkItemTools:
    def __init__(self, work_item=None):
        self.system = FakeStore(work_item or _work_item())


def _work_item(status=WorkItemStatus.READY_FOR_ANALYSIS, **updates):
    values = {
        "id": "7",
        "title": "Demo",
        "description": "Build it.",
        "status": status.value,
        "type": WorkItemType.TASK,
        "assignees": [],
        "comments": [],
    }
    values.update(updates)
    return WorkItem(**values)


def _service(work_item=None):
    return DelegationService(
        FakeWorkItemTools(work_item),
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


def test_entry_rejects_agent_that_does_not_own_current_phase():
    service = _service()

    with pytest.raises(DelegationRejectedError, match="owned by 'Requirements'"):
        service._validate_entry("Developer", "7")


def test_entry_rejects_running_agent_run():
    service = _service()
    service.ticket_tools.system.running_run = SimpleNamespace(
        id="41",
        agent_name="Requirements",
    )

    with pytest.raises(DelegationRejectedError, match=r"RUNNING agent run #41"):
        service._validate_entry("Requirements", "7")


def test_entry_rejects_unresolved_dependencies():
    service = _service()
    service.ticket_tools.system.blockers = ["2", "5"]

    with pytest.raises(DelegationRejectedError, match=r"#2, #5"):
        service._validate_entry("Requirements", "7")


def test_entry_rejects_missing_required_artifact():
    service = _service(_work_item(WorkItemStatus.READY_FOR_REVIEW))

    with pytest.raises(
        DelegationRejectedError, match="missing required entry artifacts"
    ):
        service._validate_entry("QM", "7")


def test_entry_rejects_missing_required_gate():
    service = _service(
        _work_item(
            WorkItemStatus.READY_FOR_DESIGN,
            gate_analysis_status=GateStatus.PENDING,
        )
    )

    with pytest.raises(DelegationRejectedError, match="approved entry gates: analysis"):
        service._validate_entry("Architect", "7")


def test_entry_clean_worktree_check_is_role_aware(monkeypatch):
    requirement_service = _service()
    monkeypatch.setattr(
        requirement_service,
        "_check_clean_git_status",
        lambda: "BLOCK: dirty",
    )
    with pytest.raises(DelegationRejectedError, match="dirty"):
        requirement_service._validate_entry("Requirements", "7")

    qm_item = _work_item(
        WorkItemStatus.READY_FOR_REVIEW,
        artifacts=[ArtifactLink(title="Requirement", url="docs/requirements/REQ-7.md")],
    )
    qm_service = _service(qm_item)
    monkeypatch.setattr(
        qm_service,
        "_check_clean_git_status",
        lambda: pytest.fail("QM must not require a clean worktree at entry"),
    )

    work_item, workflow = qm_service._validate_entry("QM", "7")

    assert work_item.id == "7"
    assert workflow.owner == "QM"


def test_success_postconditions_require_artifact_gate_verification_and_clean_git():
    service = _service()
    work_item = _work_item()
    workflow = SimpleNamespace(
        required_artifact_pattern="docs/requirements/REQ-*.md",
        gate_to_update="analysis",
        requires_verification=True,
        requires_clean_worktree=True,
    )
    completion = AgentCompletion(status="SUCCESS", summary="Done")

    result, diagnostics = service._validate_success_postconditions(
        "Requirements",
        work_item,
        workflow,
        completion,
        {"status_short": " M docs/requirements/REQ-7.md"},
        {},
    )

    assert result.status.value == "FAILED"
    assert "Missing required output artifact" in result.details
    assert "Completion must approve the 'analysis' gate" in result.details
    assert "At least one verification result is required" in result.details
    assert "final Git worktree is not clean" in result.details
    assert diagnostics["failure_kind"] == "postcondition_failure"


def test_success_postconditions_accept_complete_typed_result():
    service = _service()
    work_item = _work_item()
    workflow = SimpleNamespace(
        required_artifact_pattern="docs/requirements/REQ-*.md",
        gate_to_update="analysis",
        requires_verification=True,
        requires_clean_worktree=True,
    )
    completion = AgentCompletion.model_validate(
        {
            "status": "SUCCESS",
            "summary": "Done",
            "artifacts": [
                {
                    "title": "Requirement",
                    "url": "docs/requirements/REQ-7.md",
                }
            ],
            "gate_decision": {
                "gate": "analysis",
                "decision": "Approved",
            },
            "verification": [{"name": "lint", "status": "PASSED"}],
        }
    )

    result, diagnostics = service._validate_success_postconditions(
        "Requirements", work_item, workflow, completion, {"status_short": ""}, {}
    )

    assert result is completion
    assert diagnostics == {}


def test_failure_finalization_preserves_resumable_status_and_diagnostics():
    service = _service()
    work_item = _work_item()
    workflow = get_policy().workflow[work_item.status]
    completion = AgentCompletion(
        status="FAILED",
        summary="Could not write requirement.",
        details="Template was missing.",
        blockers=["Need requirements template."],
    )

    finalization = service._build_finalization(
        agent_name="Requirements",
        work_item=work_item,
        workflow=workflow,
        run_status=AgentRunStatus.FAILED,
        completion=completion,
        evidence={"latest_commit": "def456", "changed_files": ["partial.md"]},
        raw_response="raw",
        diagnostics={"failure_kind": "exception"},
        starting_commit="abc123",
    )

    assert finalization.exit_status == WorkItemStatus.BLOCKED.value
    assert finalization.resumable_status == WorkItemStatus.READY_FOR_ANALYSIS.value
    assert "Need requirements template." in finalization.blocked_reason
    assert "Template was missing." in finalization.comment
    assert finalization.commit_hashes == ["def456"]
    assert finalization.diagnostics == {"failure_kind": "exception"}
    assert "Changed files: partial.md" in finalization.handoff_context


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
