import pytest

from src.ariadne.policies import evaluator
from src.ariadne.policies.evaluator import PolicyDecision, evaluate_tool_call
from src.ariadne.policies.loader import get_policy
from src.ariadne.runtime.context import (
    DelegationContext,
    delegation_scope,
    get_active_delegation,
    set_active_work_item_id,
)
from src.ariadne.tools import tool_wrapper
from src.ariadne.work_items.models import WorkItem, WorkItemStatus, WorkItemType


@pytest.fixture(autouse=True)
def reset_runtime_context():
    set_active_work_item_id(None)
    yield
    set_active_work_item_id(None)


def _work_item(status=WorkItemStatus.READY_FOR_ANALYSIS):
    return WorkItem(
        id="7",
        title="Demo",
        description="Build it.",
        status=status.value,
        type=WorkItemType.TASK,
        assignees=[],
        comments=[],
    )


def _install_work_item(monkeypatch, work_item):
    monkeypatch.setattr(evaluator, "_get_work_item", lambda work_item_id: work_item)
    monkeypatch.setattr(evaluator, "_get_blockers", lambda work_item_id: [])
    set_active_work_item_id(work_item.id)


def test_delegation_scope_restores_previous_identity():
    context = DelegationContext(
        work_item_id="7",
        agent_name="Requirements",
        agent_run_id="41",
        entry_status=WorkItemStatus.READY_FOR_ANALYSIS.value,
    )

    assert get_active_delegation() is None
    with delegation_scope(context):
        assert get_active_delegation() == context
    assert get_active_delegation() is None


def test_policy_rejects_bound_agent_identity_mismatch():
    context = DelegationContext(
        work_item_id="7",
        agent_name="Requirements",
        agent_run_id="41",
        entry_status=WorkItemStatus.READY_FOR_ANALYSIS.value,
    )

    with delegation_scope(context):
        decision = evaluate_tool_call("read_file", agent_name="Developer")

    assert not decision.allowed
    assert "belongs to 'Requirements'" in decision.reason


def test_policy_rejects_specialist_that_does_not_own_workflow_state(monkeypatch):
    work_item = _work_item(WorkItemStatus.READY_FOR_DEVELOPMENT)
    _install_work_item(monkeypatch, work_item)
    context = DelegationContext(
        work_item_id="7",
        agent_name="Requirements",
        agent_run_id="41",
        entry_status=work_item.status,
    )

    with delegation_scope(context):
        decision = evaluate_tool_call("write_file", agent_name="Requirements")

    assert not decision.allowed
    assert "owned by 'Developer', not 'Requirements'" in decision.reason


def test_policy_rejects_tool_targeting_another_work_item(monkeypatch):
    work_item = _work_item()
    _install_work_item(monkeypatch, work_item)
    context = DelegationContext(
        work_item_id="7",
        agent_name="Requirements",
        agent_run_id="41",
        entry_status=work_item.status,
    )

    with delegation_scope(context):
        decision = evaluate_tool_call(
            "post_comment",
            {"work_item_id": "8", "comment": "wrong ticket"},
            agent_name="Requirements",
        )

    assert not decision.allowed
    assert "targeted work item #8" in decision.reason


def test_coordinator_only_tool_is_denied_even_if_override_exposes_it(monkeypatch):
    policy = get_policy().model_copy(deep=True)
    policy.agents["Requirements"].tools.append("update_status")
    monkeypatch.setattr(evaluator, "get_policy", lambda: policy)

    decision = evaluate_tool_call("update_status", agent_name="Requirements")

    assert not decision.allowed
    assert "coordinator-owned" in decision.reason


def test_tool_wrapper_passes_bound_agent_identity(monkeypatch):
    captured = {}

    def read_file(file_path):
        return file_path

    def evaluate(tool_name, args, *, agent_name):
        captured.update(tool_name=tool_name, args=args, agent_name=agent_name)
        return PolicyDecision()

    monkeypatch.setattr(tool_wrapper, "evaluate_tool_call", evaluate)
    wrapped = tool_wrapper.with_error_handling(read_file, agent_name="Architect")

    assert wrapped("docs/design.md") == "docs/design.md"
    assert captured == {
        "tool_name": "read_file",
        "args": {"args": ["docs/design.md"]},
        "agent_name": "Architect",
    }


def test_specialist_workflow_does_not_expose_status_transition():
    policy = get_policy()

    for status, workflow in policy.workflow.items():
        if workflow.owner not in {"Orchestrator", "None"}:
            assert "update_status" not in workflow.allowed_tools, status
