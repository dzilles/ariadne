import functools
from typing import Callable, Any

from src.workflows.context import get_active_ticket_id
from src.interfaces.plane_adapter import PlaneTicketSystem
from src.workflows.rules import get_rule_for_status

def get_ticket_system():
    # Return a new instance every time to ensure we get fresh data from Plane
    return PlaneTicketSystem()

def jit_vmodel_guard(func: Callable) -> Callable:

    """

    Decorator for write/commit tools that checks the JIT context and workflow rules.

    It retrieves the active_ticket_id, checks its status in Plane, and ensures

    the tool execution is allowed for the current ticket state.

    """

    @functools.wraps(func)

    def wrapper(*args: Any, **kwargs: Any) -> Any:

        # 1. Retrieve the active_ticket_id from the hidden context

        ticket_id = get_active_ticket_id()

        if not ticket_id:

            return (

                "⛔ BLOCK: You cannot execute mutating tools without an active ticket context. "

                "The Orchestrator must delegate a ticket to you."

            )



        # 2. Query Plane for that ticket's status and blockers

        try:

            ts = get_ticket_system()

            ticket = ts.get_ticket(ticket_id)

            

            # Check for blockers using Plane interaction directly if needed

            # For now, we rely on the rule engine based on status

            relations = ts.client.get_issue_relations(ticket.id)

            for rel in relations:

                if isinstance(rel, dict) and rel.get("relation_type") == "blocked_by":

                    return f"⛔ BLOCK: Ticket #{ticket_id} is currently BLOCKED by another issue."



        except Exception as e:

            return f"System Error: Could not verify ticket status for #{ticket_id}. {e}"



        # 3. Block execution if wrong state

        status = ticket.status or "Backlog"

        rule = get_rule_for_status(status)

        if not rule:

            return f"System Error: No workflow rule defined for status '{status}'."



        tool_name = func.__name__

        if tool_name not in rule.allowed_actions:

            return (

                f"⛔ ACTION BLOCKED: You cannot perform '{tool_name}' "

                f"because Ticket #{ticket_id} is in '{status}'.\n"

                f"Your allowed actions for this phase are: {rule.allowed_actions}"

            )



        # Execute the original tool

        return func(*args, **kwargs)



    return wrapper


