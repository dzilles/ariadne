from src.ariadne.work_items.models import GateStatus, WorkItemStatus, WorkItemStore
from src.ariadne.workflows.enforcement import jit_vmodel_guard
from src.ariadne.runtime.context import (
    get_active_work_item_id,
    notify_active_work_item_changed,
    set_active_work_item_id,
)


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
                f"Created At: {work_item.created_at}",
                f"Updated At: {work_item.updated_at}",
                f"Relevant Commits: {', '.join(work_item.commit_hashes) if work_item.commit_hashes else 'None'}",
                f"Target Branch: {work_item.target_branch or 'Not set'}",
                f"Feature Branch: {work_item.feature_branch or 'Not set'}",
                f"Base Commit: {work_item.base_commit or 'Not set'}",
                f"Merge Request ID: {work_item.merge_request_id or 'Not set'}",
                f"Assignees: {', '.join(work_item.assignees)}",
                "\n--- Description ---",
                work_item.description,
                "\n--- Shared Context ---",
                work_item.shared_context or "No shared context recorded.",
                "\n--- Tool Logs ---",
            ]

            if work_item.tool_logs:
                for entry in work_item.tool_logs:
                    lines.append(f"- [{entry.timestamp}] {entry.tool_name} ({entry.status})")
                    if entry.result:
                        lines.append(f"  Result: {entry.result[:200]}")
            else:
                lines.append("No tool logs recorded.")

            lines.extend([
                "\n--- Comments ---"
            ])
            
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

    def get_work_item_info(self, work_item_id: str) -> str:
        """Orchestrator-facing alias for get_work_item."""
        return self.get_work_item(work_item_id)

    def list_work_items(self) -> str:
        """List all work items with ID, title, status, and type."""
        try:
            work_items = self.system.list_work_items()
            if not work_items:
                return "No work items found."

            lines = ["Work Items:"]
            for item in work_items:
                lines.append(
                    f"- #{item.id}: {item.title} | Status: {item.status} | Type: {item.type.value}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Error listing work items: {e}"

    def activate_work_item(self, work_item_id: str) -> str:
        """
        Activate a work item for the current run without delegating to another agent.
        This sets the active work-item context used by guarded tools and the UI header.
        """
        try:
            work_item = self.system.get_work_item(work_item_id)
            set_active_work_item_id(work_item.id)
            return (
                f"Success: Activated work item #{work_item.id}: "
                f"{work_item.title} ({work_item.status})"
            )
        except Exception as e:
            return f"Error activating work item: {e}"

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
            if get_active_work_item_id() == str(work_item_id):
                notify_active_work_item_changed(work_item_id)
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

    @jit_vmodel_guard
    def add_commit_hash(self, work_item_id: str, commit_hash: str) -> str:
        """Record a git commit hash that is relevant to this work item."""
        try:
            self.system.add_commit_hash(work_item_id, commit_hash)
            return f"Success: Added commit {commit_hash} to work item {work_item_id}"
        except Exception as e:
            return f"Error adding commit hash: {e}"

    @jit_vmodel_guard
    def append_shared_context(self, work_item_id: str, author: str, context: str) -> str:
        """Append context for the next agent working on this work item."""
        try:
            self.system.append_shared_context(work_item_id, author, context)
            return f"Success: Appended shared context to work item {work_item_id}"
        except Exception as e:
            return f"Error appending shared context: {e}"

    @jit_vmodel_guard
    def update_git_metadata(
        self,
        work_item_id: str,
        target_branch: str | None = None,
        feature_branch: str | None = None,
        base_commit: str | None = None,
        merge_request_id: str | None = None,
    ) -> str:
        """Update branch, base commit, and merge request metadata for this work item."""
        try:
            self.system.update_git_metadata(
                work_item_id=work_item_id,
                target_branch=target_branch,
                feature_branch=feature_branch,
                base_commit=base_commit,
                merge_request_id=merge_request_id,
            )
            return f"Success: Updated git metadata for work item {work_item_id}"
        except Exception as e:
            return f"Error updating git metadata: {e}"
            
    def get_tool_descriptions(self, include_context_writer: bool = False) -> str:
        allowed_statuses = ", ".join([f"'{s.value}'" for s in WorkItemStatus])
        descriptions = f"""
### Work Item Tools
*   `get_work_item(work_item_id)`: Get full work item details (User Story, Status, Comments).
*   `get_work_item_info(work_item_id)`: Orchestrator-facing alias for `get_work_item`.
*   `get_ticket(ticket_id)`: Backward-compatible alias for `get_work_item`.
*   `list_work_items()`: List all work items with ID, title, status, and type.
*   `activate_work_item(work_item_id)`: Activate a work item for the current run without delegating to another agent.
*   `update_status(work_item_id, status)`: Move work item workflow. Allowed values: {allowed_statuses}
*   `post_comment(work_item_id, comment)`: Add a comment.
*   `approve_gate(work_item_id, gate)`: Mark a phase as Approved (analysis, design, test).
*   `reject_gate(work_item_id, gate)`: Mark a phase as Rejected.
*   `add_link(work_item_id, title, url, comment)`: Link an output artifact (doc/file) to the work item. Can optionally post a comment summarizing changes.
*   `add_commit_hash(work_item_id, commit_hash)`: Record a git commit hash relevant to the work item.
*   `update_git_metadata(work_item_id, target_branch=None, feature_branch=None, base_commit=None, merge_request_id=None)`: Update branch, base commit, and merge request metadata.
"""
        if include_context_writer:
            descriptions += "*   `append_shared_context(work_item_id, author, context)`: Orchestrator-only tool for appending handoff context for later agents.\n"
        return descriptions


# Backwards-compatible name while callers are migrated.
StandardTicketTools = WorkItemTools
