from src.ariadne.work_items.models import GateStatus, WorkItemStatus, WorkItemStore
from src.ariadne.workflows.enforcement import jit_vmodel_guard


class WorkItemTools:
    """
    Agent-facing tools for reading and updating work items.
    """

    def __init__(self, system: WorkItemStore):
        self.system = system

    def get_work_item(self, work_item_id: str) -> str:
        """
        Get details of a work item.
        """
        try:
            work_item = self.system.get_work_item(work_item_id)
            
            # Format as readable string for LLM
            lines = [
                f"ID: {work_item.id}",
                f"Title: {work_item.title}",
                f"Status: {work_item.status}",
                f"Type: {work_item.type.value}",
                f"Assignees: {', '.join(work_item.assignees)}",
                "\n--- Description ---",
                work_item.description,
                "\n--- Comments ---"
            ]
            
            for c in work_item.comments:
                lines.append(f"- [{c.author}]: {c.text}")
                
            lines.append("\n--- Artifacts ---")
            for a in work_item.artifacts:
                lines.append(f"- {a.title}: {a.url}")
                
            return "\n".join(lines)
        except Exception as e:
            return f"Error fetching work item: {e}"

    def get_ticket(self, ticket_id: str) -> str:
        """Backward-compatible alias for get_work_item."""
        return self.get_work_item(ticket_id)

    @jit_vmodel_guard
    def update_status(self, work_item_id: str, status: str) -> str:
        """
        Update work item status.
        Allowed values are dynamically defined by the WorkItemStatus enum.
        (e.g., 'Ready for Analysis', 'Ready for Review', 'Ready for Design', 'Blocked', 'Done')
        """
        try:
            # Map string to Enum
            enum_status = WorkItemStatus(status)
            self.system.update_status(work_item_id, enum_status)
            return f"Success: Work item {work_item_id} moved to {status}"
        except ValueError:
            return f"Error: Invalid status '{status}'. Allowed: {[s.value for s in WorkItemStatus]}"
        except Exception as e:
            return f"Error updating status: {e}"

    @jit_vmodel_guard
    def post_comment(self, work_item_id: str, comment: str) -> str:
        """Post a comment to the work item."""
        try:
            self.system.post_comment(work_item_id, comment)
            return f"Success: Comment added to {work_item_id}"
        except Exception as e:
            return f"Error posting comment: {e}"

    @jit_vmodel_guard
    def approve_gate(self, work_item_id: str, gate: str) -> str:
        """
        Approve a specific phase gate.
        gate: 'analysis', 'design', 'test'
        """
        try:
            self.system.set_gate_status(work_item_id, gate, GateStatus.APPROVED)
            return f"Success: {gate} gate APPROVED for {work_item_id}"
        except Exception as e:
            return f"Error approving gate: {e}"

    @jit_vmodel_guard
    def reject_gate(self, work_item_id: str, gate: str) -> str:
        """
        Reject a specific phase gate.
        gate: 'analysis', 'design', 'test'
        """
        try:
            self.system.set_gate_status(work_item_id, gate, GateStatus.REJECTED)
            return f"Success: {gate} gate REJECTED for {work_item_id}"
        except Exception as e:
            return f"Error rejecting gate: {e}"
    
    @jit_vmodel_guard
    def add_link(self, work_item_id: str, title: str, url: str, comment: str = None) -> str:
        """Link an artifact (URL) to the work item and optionally post a comment."""
        try:
            self.system.add_artifact_link(work_item_id, title, url, comment)
            msg = f"Success: Linked {title} to {work_item_id}"
            if comment:
                msg += " and added comment"
            return msg
        except Exception as e:
            return f"Error adding link: {e}"
            
    def get_tool_descriptions(self) -> str:
        allowed_statuses = ", ".join([f"'{s.value}'" for s in WorkItemStatus])
        return f"""
### Work Item Tools
*   `get_work_item(work_item_id)`: Get full work item details (User Story, Status, Comments).
*   `get_ticket(ticket_id)`: Backward-compatible alias for `get_work_item`.
*   `update_status(work_item_id, status)`: Move work item workflow. Allowed values: {allowed_statuses}
*   `post_comment(work_item_id, comment)`: Add a comment.
*   `approve_gate(work_item_id, gate)`: Mark a phase as Approved (analysis, design, test).
*   `reject_gate(work_item_id, gate)`: Mark a phase as Rejected.
*   `add_link(work_item_id, title, url, comment)`: Link an output artifact (doc/file) to the work item. Can optionally post a comment summarizing changes.
"""


# Backwards-compatible name while callers are migrated.
StandardTicketTools = WorkItemTools
