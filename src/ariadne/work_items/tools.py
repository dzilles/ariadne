from src.ariadne.work_items.models import AgentRunStatus, GateStatus, WorkItemStatus, WorkItemStore
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

    def create_work_item(
        self,
        title: str,
        description: str,
        type: str = "Task",
        priority: str = "Medium",
    ) -> str:
        """
        Create a new work item in Backlog status.
        """
        try:
            from src.ariadne.work_items.models import WorkItemType

            work_item_type = WorkItemType(type)
            work_item_id = self.system.create_work_item(
                title=title,
                description=description,
                type=work_item_type,
                priority=priority,
            )
            return f"Success: Created work item #{work_item_id}"
        except ValueError:
            return f"Error: Invalid work item type '{type}'. Allowed: {[t.value for t in WorkItemType]}"
        except Exception as e:
            return f"Error creating work item: {e}"

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

            try:
                agent_runs = self.system.list_agent_runs(work_item_id)
            except Exception:
                agent_runs = []
            lines.append("\n--- Agent Runs ---")
            if agent_runs:
                for run in agent_runs[-5:]:
                    summary = run.completion_payload.get("summary", "")
                    lines.append(
                        f"- #{run.id} {run.agent_name} [{run.status.value}] {summary}"
                    )
            else:
                lines.append("No agent runs recorded.")

            lines.extend([
                "\n--- Comments ---"
            ])
            
            for c in work_item.comments:
                lines.append(f"- [{c.author}]: {c.text}")
                
            lines.append("\n--- Artifacts ---")
            for a in work_item.artifacts:
                suffix = f" [{a.type}]" if a.type and a.type != "link" else ""
                source = f" (agent run #{a.agent_run_id})" if a.agent_run_id else ""
                lines.append(f"- {a.title}{suffix}: {a.url}{source}")
                
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
    def add_link(
        self,
        work_item_id: str,
        title: str,
        url: str,
        comment: str = None,
        artifact_type: str = "link",
        agent_run_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Link an artifact (URL) to the work item and optionally post a comment."""
        try:
            self.system.add_artifact_link(
                work_item_id,
                title,
                url,
                comment,
                artifact_type=artifact_type,
                agent_run_id=agent_run_id,
                metadata=metadata,
            )
            msg = f"Success: Linked {title} to {work_item_id}"
            if comment:
                msg += " and added comment"
            return msg
        except Exception as e:
            return f"Error adding link: {e}"

    def delete_link(
        self,
        work_item_id: str,
        title: str | None = None,
        url: str | None = None,
    ) -> str:
        """Delete artifact links from a work item by exact title and/or URL."""
        try:
            self.system.delete_artifact_link(work_item_id, title=title, url=url)
            return f"Success: Deleted matching link from work item {work_item_id}"
        except Exception as e:
            return f"Error deleting link: {e}"

    def remove_comment(self, work_item_id: str, comment_id: str) -> str:
        """Remove a comment from a work item by comment ID."""
        try:
            self.system.remove_comment(work_item_id, comment_id)
            return f"Success: Removed comment {comment_id} from work item {work_item_id}"
        except Exception as e:
            return f"Error removing comment: {e}"

    @jit_vmodel_guard
    def add_commit_hash(self, work_item_id: str, commit_hash: str) -> str:
        """Record a git commit hash that is relevant to this work item."""
        try:
            self.system.add_commit_hash(work_item_id, commit_hash)
            return f"Success: Added commit {commit_hash} to work item {work_item_id}"
        except Exception as e:
            return f"Error adding commit hash: {e}"

    @jit_vmodel_guard
    def append_shared_context(
        self,
        work_item_id: str,
        author: str,
        context: str,
        agent_run_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Append context for the next agent working on this work item."""
        try:
            self.system.append_shared_context(
                work_item_id,
                author,
                context,
                agent_run_id=agent_run_id,
                metadata=metadata,
            )
            return f"Success: Appended shared context to work item {work_item_id}"
        except Exception as e:
            return f"Error appending shared context: {e}"

    def get_context_bundle(
        self,
        work_item_id: str,
        target_agent: str = "",
        max_entries: int = 10,
    ) -> str:
        """
        Return compact context for a delegated agent.

        This is intentionally read-only. It combines stable work item facts,
        recent structured context entries, and recent agent-run summaries.
        """
        try:
            max_entries = max(1, int(max_entries))
        except (TypeError, ValueError):
            return "Error: max_entries must be a positive integer."

        try:
            work_item = self.system.get_work_item(work_item_id)
            try:
                context_entries = self.system.list_context_entries(work_item_id)
            except Exception:
                context_entries = []
            try:
                agent_runs = self.system.list_agent_runs(work_item_id)
            except Exception:
                agent_runs = []

            lines = [
                f"Work item #{work_item.id}: {work_item.title}",
                f"Status: {work_item.status}",
                f"Type: {work_item.type.value}",
                f"Target agent: {target_agent or 'Not specified'}",
                "",
                "Description:",
                work_item.description or "No description recorded.",
                "",
                "Git metadata:",
                f"- Target branch: {work_item.target_branch or 'Not set'}",
                f"- Feature branch: {work_item.feature_branch or 'Not set'}",
                f"- Base commit: {work_item.base_commit or 'Not set'}",
                f"- Relevant commits: {', '.join(work_item.commit_hashes) if work_item.commit_hashes else 'None'}",
                "",
                "Artifacts:",
            ]

            selected_artifacts = self._select_context_artifacts(
                work_item.artifacts,
                target_agent,
                max_entries,
            )
            if selected_artifacts:
                for artifact in selected_artifacts:
                    type_label = f" [{artifact.type}]" if artifact.type and artifact.type != "link" else ""
                    source = f" from agent run #{artifact.agent_run_id}" if artifact.agent_run_id else ""
                    lines.append(f"- {artifact.title}{type_label}: {artifact.url}{source}")
                omitted = len(work_item.artifacts) - len(selected_artifacts)
                if omitted > 0:
                    lines.append(f"... omitted {omitted} less relevant artifact(s)")
            else:
                lines.append("No artifacts recorded.")

            lines.extend([
                "",
                "Recent context:",
            ])

            recent_entries = self._select_context_entries(
                context_entries,
                target_agent,
                max_entries,
            )
            if recent_entries:
                for entry in recent_entries:
                    lines.append(
                        f"- [{entry.created_at}] {entry.author} ({entry.kind}): {entry.content}"
                    )
            elif work_item.shared_context:
                lines.append(work_item.shared_context)
            else:
                lines.append("No structured context recorded.")

            lines.append("")
            lines.append("Recent agent runs:")
            recent_runs = agent_runs[-max_entries:]
            if recent_runs:
                for run in recent_runs:
                    summary = run.completion_payload.get("summary") or "No summary recorded."
                    lines.append(f"- #{run.id} {run.agent_name} [{run.status.value}]: {summary}")
            else:
                lines.append("No agent runs recorded.")

            return "\n".join(lines)
        except Exception as e:
            return f"Error building context bundle: {e}"

    def _select_context_artifacts(self, artifacts, target_agent: str, max_entries: int):
        if not artifacts:
            return []
        priorities = self._artifact_priorities(target_agent)
        if not priorities:
            return artifacts[-max_entries:]

        def score(item):
            artifact_type = (item.type or "link").lower()
            try:
                priority = priorities.index(artifact_type)
            except ValueError:
                priority = len(priorities)
            return (priority, -self._safe_int(item.id))

        return sorted(artifacts, key=score)[:max_entries]

    def _select_context_entries(self, entries, target_agent: str, max_entries: int):
        if not entries:
            return []
        target = target_agent.strip().lower()
        if not target:
            return entries[-max_entries:]

        preferred_authors = {
            "architect": {"requirements", "qm"},
            "developer": {"architect", "requirements", "tester", "qa"},
            "tester": {"developer", "architect", "requirements"},
            "qa": {"tester", "developer", "architect"},
        }.get(target, set())
        if not preferred_authors:
            return entries[-max_entries:]

        def score(entry):
            author = entry.author.strip().lower()
            preferred = 0 if author in preferred_authors else 1
            return (preferred, -self._safe_int(entry.id))

        return sorted(entries, key=score)[:max_entries]

    def _artifact_priorities(self, target_agent: str) -> list[str]:
        return {
            "architect": ["requirement", "requirements", "spec", "link"],
            "developer": ["design", "architecture", "requirement", "test", "link"],
            "tester": ["implementation", "source", "design", "requirement", "link"],
            "qa": ["test", "implementation", "source", "design", "requirement", "link"],
        }.get(target_agent.strip().lower(), [])

    def _safe_int(self, value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def start_agent_run(self, work_item_id: str, agent_name: str, task_description: str) -> str:
        """Record that an agent run has started for this work item."""
        try:
            agent_run_id = self.system.start_agent_run(
                work_item_id,
                agent_name,
                task_description,
            )
            return agent_run_id
        except Exception as e:
            return f"Error starting agent run: {e}"

    def finish_agent_run(
        self,
        agent_run_id: str,
        status: str,
        completion_payload: dict,
        evidence: dict,
    ) -> str:
        """Record completion and evidence for an agent run."""
        try:
            self.system.finish_agent_run(
                agent_run_id,
                AgentRunStatus(status),
                completion_payload,
                evidence,
            )
            return f"Success: Finished agent run {agent_run_id}"
        except ValueError:
            return f"Error: Invalid agent run status '{status}'. Allowed: {[s.value for s in AgentRunStatus]}"
        except Exception as e:
            return f"Error finishing agent run: {e}"

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
*   `get_context_bundle(work_item_id, target_agent="", max_entries=10)`: Read compact work item context, recent handoffs, and recent agent-run summaries.
*   `list_work_items()`: List all work items with ID, title, status, and type.
*   `activate_work_item(work_item_id)`: Activate a work item for the current run without delegating to another agent.
*   `update_status(work_item_id, status)`: Move work item workflow. Allowed values: {allowed_statuses}
*   `post_comment(work_item_id, comment)`: Add a comment.
*   `approve_gate(work_item_id, gate)`: Mark a phase as Approved (analysis, design, test).
*   `reject_gate(work_item_id, gate)`: Mark a phase as Rejected.
*   `add_link(work_item_id, title, url, comment=None, artifact_type="link", agent_run_id=None, metadata=None)`: Link an output artifact (doc/file) to the work item. Can optionally post a comment summarizing changes.
*   `add_commit_hash(work_item_id, commit_hash)`: Record a git commit hash relevant to the work item.
*   `update_git_metadata(work_item_id, target_branch=None, feature_branch=None, base_commit=None, merge_request_id=None)`: Update branch, base commit, and merge request metadata.
"""
        if include_context_writer:
            descriptions += "*   `append_shared_context(work_item_id, author, context, agent_run_id=None, metadata=None)`: Orchestrator-only tool for appending handoff context for later agents.\n"
        return descriptions


# Backwards-compatible name while callers are migrated.
StandardTicketTools = WorkItemTools
