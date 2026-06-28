import functools
from typing import Any, Callable

from src.ariadne.runtime.context import get_active_work_item_id
from src.ariadne.workflows.rules import get_rule_for_status


def get_work_item_store():
    # Deferred import to break circular dependency.
    from src.ariadne.infrastructure.container import DependencyRegistry

    return DependencyRegistry.get_work_item_tools().system


def get_ticket_system():
    """Backward-compatible alias for older tests and scripts."""
    return get_work_item_store()


def jit_vmodel_guard(func: Callable) -> Callable:
    """
    Decorator for mutating tools that checks active work-item context and
    V-model workflow rules before allowing execution.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        work_item_id = get_active_work_item_id()
        if not work_item_id:
            return (
                "⛔ BLOCK: You cannot execute mutating tools without an active work item context. "
                "The Orchestrator must delegate a work item to you."
            )

        try:
            store = get_ticket_system()
            get_work_item = getattr(store, "get_work_item", None)
            work_item = get_work_item(work_item_id) if get_work_item else store.get_ticket(work_item_id)

            get_blockers = getattr(store, "get_blockers", None)
            blockers = get_blockers(work_item.id) if get_blockers else []
            if blockers:
                return f"⛔ BLOCK: Work item #{work_item_id} is blocked by: {blockers}"
        except Exception as e:
            return f"System Error: Could not verify work item status for #{work_item_id}. {e}"

        status = work_item.status or "Backlog"
        rule = get_rule_for_status(status)
        if not rule:
            return f"System Error: No workflow rule defined for status '{status}'."

        tool_name = func.__name__
        if tool_name not in rule.allowed_actions:
            return (
                f"⛔ ACTION BLOCKED: You cannot perform '{tool_name}' "
                f"because work item #{work_item_id} is in '{status}'.\n"
                f"Your allowed actions for this phase are: {rule.allowed_actions}"
            )

        if tool_name == "update_status":
            target_status = kwargs.get("status")
            if not target_status and len(args) > 2:
                target_status = args[2]

            if target_status:
                from src.ariadne.work_items.models import WorkItemStatus

                allowed_next = [WorkItemStatus.BLOCKED.value]
                if rule.next_state:
                    allowed_next.append(rule.next_state.value)

                if target_status not in allowed_next and target_status != status:
                    return (
                        f"⛔ STATE TRANSITION BLOCKED: Cannot move work item from "
                        f"'{status}' to '{target_status}'. Allowed next states: {allowed_next}"
                    )

        return func(*args, **kwargs)

    return wrapper
