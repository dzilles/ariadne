import functools
from typing import Callable, Optional
from src.workflows.rules import get_rule_for_status, generate_instructions
from src.interfaces.ticket_system import TicketSystem

class ToolGuard:
    """
    Middleware that strictly enforces Workflow Rules on tool execution.
    Discovery tools are bypassed (read-only); Mutating tools are guarded.
    """

    # List of tools that are always allowed regardless of context or rules
    READ_ONLY_BYPASS = [
        "get_ticket",
        "search_tickets",
        "list_files",
        "read_file",
        "search_files",
        "get_status",
        "get_current_branch",
        "activate_ticket" # Self-referential
    ]

    def __init__(self, ticket_system: TicketSystem, agent_name: str):
        self.ticket_system = ticket_system
        self.agent_name = agent_name
        self.current_ticket_id: Optional[str] = None

    def activate_ticket(self, ticket_id: str) -> str:
        """
        Tool for the Agent to explicitly switch context.
        Verifies if the Agent is ALLOWED to own this ticket.
        """
        try:
            # 1. Fetch Ticket
            ticket = self.ticket_system.get_ticket(ticket_id)
            
            # 2. Get Rule
            rule = get_rule_for_status(ticket.status)
            if not rule:
                return f"System Error: No rule defined for status '{ticket.status}'."

            # 3. Check Ownership
            if rule.agent_name != self.agent_name:
                return (
                    f"⛔ ACCESS DENIED: Ticket #{ticket_id} is in '{ticket.status}'.\n"
                    f"Owner Role: {rule.agent_name}\n"
                    f"Your Role: {self.agent_name}\n"
                    f"You are not allowed to activate this ticket."
                )

            # 4. Success - Set Context
            self.current_ticket_id = ticket_id
            
            # 5. Return Instructions
            return (
                f"✅ Ticket #{ticket_id} ACTIVATED.\n"
                f"{generate_instructions(rule, ticket_id)}"
            )

        except Exception as e:
            return f"Error activating ticket: {e}"

    def guard(self, tool_name: str, func: Callable) -> Callable:
        """
        Decorator-like wrapper that checks rules before executing a tool.
        """
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 1. Bypass check for Read-Only tools
            if tool_name in self.READ_ONLY_BYPASS:
                 return func(*args, **kwargs)

            # 2. Context check for Mutating tools
            if not self.current_ticket_id:
                return (
                    f"⛔ BLOCK: You tried to use '{tool_name}' but have not activated a ticket yet.\n"
                    f"You must use `activate_ticket(ticket_id)` first to start your mission."
                )

            # 3. Rule fetching (Double check it hasn't changed)
            try:
                ticket = self.ticket_system.get_ticket(self.current_ticket_id)
            except Exception as e:
                return f"System Error: Could not verify ticket status for #{self.current_ticket_id}. {e}"

            rule = get_rule_for_status(ticket.status)
            if not rule:
                return f"System Error: No workflow rule defined for status '{ticket.status}'."

            # 4. Rule Compliance check
            if tool_name not in rule.allowed_actions:
                 return (
                     f"⛔ ACTION BLOCKED: You cannot perform '{tool_name}' "
                     f"because Ticket #{self.current_ticket_id} is in '{ticket.status}'.\n"
                     f"Your allowed actions for this phase are: {rule.allowed_actions}"
                 )

            # 5. Execute
            return func(*args, **kwargs)

        return wrapper

    def wrap_tools(self, tools: list) -> list:
        """
        Wraps a list of callables with the guard.
        """
        wrapped = []
        for tool in tools:
            func = tool if callable(tool) else getattr(tool, "func", tool)
            name = getattr(tool, "name", func.__name__)
            
            guarded = self.guard(name, func)
            wrapped.append(guarded)
            
        return wrapped
