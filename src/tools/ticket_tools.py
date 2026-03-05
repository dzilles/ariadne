from src.interfaces.ticket_system import TicketSystem, TicketStatus, GateStatus
from src.workflows.enforcement import jit_vmodel_guard

class StandardTicketTools:
    """
    Standardized tools for interacting with any Ticket System (Plane, Jira, etc.)
    via the TicketSystem interface.
    """

    def __init__(self, system: TicketSystem):
        self.system = system

    def get_ticket(self, ticket_id: str) -> str:
        """
        Get details of a ticket.
        """
        try:
            ticket = self.system.get_ticket(ticket_id)
            
            # Format as readable string for LLM
            lines = [
                f"ID: {ticket.id}",
                f"Title: {ticket.title}",
                f"Status: {ticket.status}",
                f"Type: {ticket.type.value}",
                f"Assignees: {', '.join(ticket.assignees)}",
                "\n--- Description ---",
                ticket.description,
                "\n--- Comments ---"
            ]
            
            for c in ticket.comments:
                lines.append(f"- [{c.author}]: {c.text}")
                
            lines.append("\n--- Artifacts ---")
            for a in ticket.artifacts:
                lines.append(f"- {a.title}: {a.url}")
                
            return "\n".join(lines)
        except Exception as e:
            return f"Error fetching ticket: {e}"

    @jit_vmodel_guard
    def update_status(self, ticket_id: str, status: str) -> str:
        """
        Update ticket status.
        Allowed values are dynamically defined by the TicketStatus enum.
        (e.g., 'Ready for Analysis', 'Ready for Review', 'Ready for Design', 'Blocked', 'Done')
        """
        try:
            # Map string to Enum
            enum_status = TicketStatus(status)
            self.system.update_status(ticket_id, enum_status)
            return f"Success: Ticket {ticket_id} moved to {status}"
        except ValueError:
            return f"Error: Invalid status '{status}'. Allowed: {[s.value for s in TicketStatus]}"
        except Exception as e:
            return f"Error updating status: {e}"

    @jit_vmodel_guard
    def post_comment(self, ticket_id: str, comment: str) -> str:
        """Post a comment to the ticket."""
        try:
            self.system.post_comment(ticket_id, comment)
            return f"Success: Comment added to {ticket_id}"
        except Exception as e:
            return f"Error posting comment: {e}"

    @jit_vmodel_guard
    def approve_gate(self, ticket_id: str, gate: str) -> str:
        """
        Approve a specific phase gate.
        gate: 'analysis', 'design', 'test'
        """
        try:
            self.system.set_gate_status(ticket_id, gate, GateStatus.APPROVED)
            return f"Success: {gate} gate APPROVED for {ticket_id}"
        except Exception as e:
            return f"Error approving gate: {e}"

    @jit_vmodel_guard
    def reject_gate(self, ticket_id: str, gate: str) -> str:
        """
        Reject a specific phase gate.
        gate: 'analysis', 'design', 'test'
        """
        try:
            self.system.set_gate_status(ticket_id, gate, GateStatus.REJECTED)
            return f"Success: {gate} gate REJECTED for {ticket_id}"
        except Exception as e:
            return f"Error rejecting gate: {e}"
    
    @jit_vmodel_guard
    def add_link(self, ticket_id: str, title: str, url: str, comment: str = None) -> str:
        """Link an artifact (URL) to the ticket and optionally post a comment."""
        try:
            self.system.add_artifact_link(ticket_id, title, url, comment)
            msg = f"Success: Linked {title} to {ticket_id}"
            if comment:
                msg += " and added comment"
            return msg
        except Exception as e:
            return f"Error adding link: {e}"
            
    def get_tool_descriptions(self) -> str:
        allowed_statuses = ", ".join([f"'{s.value}'" for s in TicketStatus])
        return f"""
### Ticket System Tools
*   `get_ticket(ticket_id)`: Get full ticket details (User Story, Status, Comments).
*   `update_status(ticket_id, status)`: Move ticket workflow. Allowed values: {allowed_statuses}
*   `post_comment(ticket_id, comment)`: Add a comment.
*   `approve_gate(ticket_id, gate)`: Mark a phase as Approved (analysis, design, test).
*   `reject_gate(ticket_id, gate)`: Mark a phase as Rejected.
*   `add_link(ticket_id, title, url, comment)`: Link an output artifact (doc/file) to the ticket. Can optionally post a comment summarizing changes.
"""