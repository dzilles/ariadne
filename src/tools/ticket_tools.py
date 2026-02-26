from src.interfaces.ticket_system import TicketSystem, TicketStatus, GateStatus

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
                f"Status: {ticket.status.value}",
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

    def update_status(self, ticket_id: str, status: str) -> str:
        """
        Update ticket status.
        Allowed values: 'Backlog', 'Ready for Analysis', 'Ready for Design', 
        'Ready for Development', 'Ready for Testing', 'Ready for QA', 'Done'
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

    def post_comment(self, ticket_id: str, comment: str) -> str:
        """Post a comment to the ticket."""
        try:
            self.system.post_comment(ticket_id, comment)
            return f"Success: Comment added to {ticket_id}"
        except Exception as e:
            return f"Error posting comment: {e}"

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
    
    def add_link(self, ticket_id: str, title: str, url: str) -> str:
        """Link an artifact (URL) to the ticket."""
        try:
            self.system.add_artifact_link(ticket_id, title, url)
            return f"Success: Linked {title} to {ticket_id}"
        except Exception as e:
            return f"Error adding link: {e}"
            
    def get_tool_descriptions(self) -> str:
        return """
### Ticket System Tools
*   `get_ticket(ticket_id)`: Get full ticket details (User Story, Status, Comments).
*   `update_status(ticket_id, status)`: Move ticket workflow (e.g., "Ready for Design").
*   `post_comment(ticket_id, comment)`: Add a comment.
*   `approve_gate(ticket_id, gate)`: Mark a phase as Approved (analysis, design, test).
*   `reject_gate(ticket_id, gate)`: Mark a phase as Rejected.
*   `add_link(ticket_id, title, url)`: Link an output artifact (doc/file) to the ticket.
"""
