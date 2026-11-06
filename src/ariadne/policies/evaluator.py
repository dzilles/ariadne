"""Evaluate configured tool policies for a proposed tool call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .loader import get_policy


@dataclass(frozen=True)
class PolicyDecision:
    """Result of evaluating a tool call against policy."""

    allowed: bool = True
    requires_user_permission: bool = False
    reason: str = ""

    @classmethod
    def deny(cls, reason: str) -> "PolicyDecision":
        return cls(allowed=False, reason=reason)

    def with_user_permission(self) -> "PolicyDecision":
        return PolicyDecision(
            allowed=self.allowed,
            requires_user_permission=True,
            reason=self.reason,
        )


def tool_requires_user_permission(tool_name: str) -> bool:
    """Return True when the tool policy includes the user-permission check."""
    policy = get_policy()
    tool = policy.tools.get(tool_name)
    return bool(tool and "user_permission" in tool.checks)


def evaluate_tool_call(
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    agent_name: str | None = None,
    check_user_permission: bool = True,
    check_work_item: bool = True,
) -> PolicyDecision:
    """Evaluate a tool call against agent, user, and work-item checks."""
    args = args or {}
    policy = get_policy()
    tool = policy.tools.get(tool_name)
    if not tool:
        return PolicyDecision.deny(f"Tool '{tool_name}' is not defined in policy.")

    from src.ariadne.runtime.context import get_active_delegation

    delegation = get_active_delegation()
    if delegation and agent_name and delegation.agent_name != agent_name:
        return PolicyDecision.deny(
            f"ACTION BLOCKED: Delegation run #{delegation.agent_run_id} belongs to "
            f"'{delegation.agent_name}', not '{agent_name}'."
        )
    if delegation and not agent_name:
        agent_name = delegation.agent_name

    if agent_name:
        agent = policy.agents.get(agent_name)
        if not agent:
            return PolicyDecision.deny(
                f"Agent '{agent_name}' is not defined in policy."
            )
        if tool_name not in agent.tools:
            return PolicyDecision.deny(
                f"Agent '{agent_name}' is not allowed to use '{tool_name}'."
            )

    if tool.coordinator_only and agent_name not in {None, "Orchestrator"}:
        return PolicyDecision.deny(
            f"ACTION BLOCKED: '{tool_name}' is coordinator-owned and cannot be "
            f"used by specialist '{agent_name}'."
        )

    decision = PolicyDecision()
    if check_user_permission and "user_permission" in tool.checks:
        decision = decision.with_user_permission()

    if check_work_item and _has_work_item_checks(tool.checks):
        work_item_decision = _evaluate_work_item_checks(
            tool_name,
            args,
            tool,
            agent_name=agent_name,
        )
        if not work_item_decision.allowed:
            return work_item_decision

    return decision


def _has_work_item_checks(checks: list[str]) -> bool:
    return any(
        check in checks
        for check in ("work_item_state", "work_item_transition", "work_item_field")
    )


def _evaluate_work_item_checks(
    tool_name: str,
    args: dict[str, Any],
    tool,
    *,
    agent_name: str | None,
) -> PolicyDecision:
    from src.ariadne.runtime.context import (
        get_active_delegation,
        get_active_work_item_id,
    )

    work_item_id = get_active_work_item_id()
    if not work_item_id:
        return PolicyDecision.deny(
            "⛔ BLOCK: You cannot execute mutating tools without an active work item context. "
            "The Orchestrator must delegate a work item to you."
        )

    delegation = get_active_delegation()
    if delegation and delegation.work_item_id != str(work_item_id):
        return PolicyDecision.deny(
            "ACTION BLOCKED: Active work-item context does not match the "
            f"delegation ticket #{delegation.work_item_id}."
        )

    requested_work_item_id = _work_item_id_arg(tool_name, args)
    if requested_work_item_id and str(requested_work_item_id) != str(work_item_id):
        return PolicyDecision.deny(
            f"ACTION BLOCKED: Tool '{tool_name}' targeted work item "
            f"#{requested_work_item_id}, but delegation is scoped to #{work_item_id}."
        )

    try:
        work_item = _get_work_item(work_item_id)
        blockers = _get_blockers(work_item.id)
        if blockers:
            return PolicyDecision.deny(
                f"⛔ BLOCK: Work item #{work_item_id} is blocked by: {blockers}"
            )
    except Exception as e:
        return PolicyDecision.deny(
            f"System Error: Could not verify work item status for #{work_item_id}. {e}"
        )

    status = work_item.status or "Backlog"
    workflow = get_policy().workflow.get(status)
    if not workflow:
        return PolicyDecision.deny(
            f"System Error: No workflow policy defined for status '{status}'."
        )

    if agent_name and agent_name != "Orchestrator" and workflow.owner != agent_name:
        return PolicyDecision.deny(
            f"ACTION BLOCKED: Work item #{work_item_id} in '{status}' is owned by "
            f"'{workflow.owner}', not '{agent_name}'."
        )

    if delegation and status != delegation.entry_status:
        return PolicyDecision.deny(
            f"ACTION BLOCKED: Work item #{work_item_id} changed from delegation "
            f"entry status '{delegation.entry_status}' to '{status}'."
        )

    workflow_tool = workflow.allowed_tools.get(tool_name)
    if "work_item_state" in tool.checks and workflow_tool is None:
        return PolicyDecision.deny(
            f"⛔ ACTION BLOCKED: You cannot perform '{tool_name}' "
            f"because work item #{work_item_id} is in '{status}'.\n"
            f"Your allowed actions for this phase are: {list(workflow.allowed_tools)}"
        )

    if "work_item_transition" in tool.checks:
        transition_decision = _evaluate_transition(
            tool_name, args, workflow_tool, status
        )
        if not transition_decision.allowed:
            return transition_decision

    if "work_item_field" in tool.checks:
        requirements = list(tool.field_requirements)
        if workflow_tool:
            requirements.extend(workflow_tool.field_requirements)
        field_decision = _evaluate_field_requirements(work_item, requirements)
        if not field_decision.allowed:
            return field_decision

    return PolicyDecision()


_WORK_ITEM_ID_TOOLS = {
    "update_status",
    "post_comment",
    "approve_gate",
    "reject_gate",
    "add_link",
    "add_commit_hash",
    "append_shared_context",
    "update_git_metadata",
}


def _work_item_id_arg(tool_name: str, args: dict[str, Any]) -> Any:
    if tool_name not in _WORK_ITEM_ID_TOOLS:
        return None
    return _arg_value(args, "work_item_id", index=0)


def _get_work_item(work_item_id: str):
    from src.ariadne.infrastructure.container import DependencyRegistry

    store = DependencyRegistry.get_work_item_tools().system
    get_work_item = getattr(store, "get_work_item", None)
    if get_work_item:
        return get_work_item(work_item_id)
    return store.get_ticket(work_item_id)


def _get_blockers(work_item_id: str) -> list:
    from src.ariadne.infrastructure.container import DependencyRegistry

    store = DependencyRegistry.get_work_item_tools().system
    get_blockers = getattr(store, "get_blockers", None)
    return get_blockers(work_item_id) if get_blockers else []


def _evaluate_transition(
    tool_name: str,
    args: dict[str, Any],
    workflow_tool,
    status: str,
) -> PolicyDecision:
    if tool_name != "update_status":
        return PolicyDecision()

    target_status = _arg_value(args, "status", index=1)
    if not target_status:
        return PolicyDecision()

    allowed_targets = list(workflow_tool.allowed_targets if workflow_tool else [])
    if target_status not in allowed_targets and target_status != status:
        return PolicyDecision.deny(
            f"⛔ STATE TRANSITION BLOCKED: Cannot move work item from "
            f"'{status}' to '{target_status}'. Allowed next states: {allowed_targets}"
        )
    return PolicyDecision()


def _evaluate_field_requirements(
    work_item, requirements: list[dict[str, Any]]
) -> PolicyDecision:
    for requirement in requirements:
        field_name = requirement.get("field")
        if not field_name:
            continue
        actual = getattr(work_item, field_name, None)
        if requirement.get("present") and not actual:
            return PolicyDecision.deny(
                f"⛔ FIELD BLOCKED: Work item field '{field_name}' is required."
            )
        if "equals" in requirement and actual != requirement["equals"]:
            return PolicyDecision.deny(
                f"⛔ FIELD BLOCKED: Work item field '{field_name}' must equal "
                f"{requirement['equals']!r}."
            )
    return PolicyDecision()


def _arg_value(args: dict[str, Any], name: str, *, index: int | None = None) -> Any:
    if name in args:
        return args[name]
    positional = args.get("args")
    if index is not None and isinstance(positional, list) and len(positional) > index:
        return positional[index]
    return None
