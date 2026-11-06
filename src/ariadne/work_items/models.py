from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, List, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class WorkItemType(str, Enum):
    FEATURE = "Feature"
    BUG = "Bug"
    TASK = "Task"


class WorkItemStatus(str, Enum):
    BACKLOG = "Backlog"
    READY_FOR_ANALYSIS = "Ready for Analysis"
    READY_FOR_REVIEW = "Ready for Review"
    READY_FOR_DESIGN = "Ready for Design"
    READY_FOR_DEVELOPMENT = "Ready for Development"
    READY_FOR_TESTING = "Ready for Testing"
    READY_FOR_QA = "Ready for QA"
    DONE = "Done"
    BLOCKED = "Blocked"


class GateStatus(str, Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class ArtifactLink(BaseModel):
    id: str = ""
    title: str
    url: str
    type: str = "link"
    agent_run_id: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class Comment(BaseModel):
    id: str
    text: str
    author: str
    created_at: str


class ToolLogEntry(BaseModel):
    timestamp: str
    tool_name: str
    status: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: str = ""


class AgentRunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkItemRelationshipType(str, Enum):
    PARENT = "PARENT"
    DEPENDS_ON = "DEPENDS_ON"
    BLOCKS = "BLOCKS"
    RELATED = "RELATED"


class AgentCompletionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class VerificationStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class CompletionArtifact(BaseModel):
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    type: str = "link"
    stable_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "url", "type", "stable_id", mode="before")
    @classmethod
    def strip_text_fields(cls, value: Any) -> str:
        return str(value or "").strip()


class VerificationResult(BaseModel):
    name: str = Field(min_length=1)
    status: VerificationStatus
    details: str = ""
    command: str = ""

    @field_validator("name", "details", "command", mode="before")
    @classmethod
    def strip_text_fields(cls, value: Any) -> str:
        return str(value or "").strip()


class GateDecision(BaseModel):
    gate: str = Field(min_length=1)
    decision: GateStatus
    rationale: str = ""

    @field_validator("gate", "rationale", mode="before")
    @classmethod
    def strip_text_fields(cls, value: Any) -> str:
        return str(value or "").strip()


class AgentCompletion(BaseModel):
    schema_version: Literal[1] = 1
    status: AgentCompletionStatus
    summary: str
    details: str = ""
    decisions: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    artifacts: list[CompletionArtifact] = Field(default_factory=list)
    verification: list[VerificationResult] = Field(default_factory=list)
    gate_decision: GateDecision | None = None

    @field_validator("summary", "details", mode="before")
    @classmethod
    def strip_text_fields(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("summary")
    @classmethod
    def require_summary(cls, value: str) -> str:
        if not value:
            raise ValueError("summary cannot be empty")
        return value

    @field_validator("decisions", "blockers", mode="before")
    @classmethod
    def normalize_text_lists(cls, values: Any) -> list[str]:
        if not values:
            return []
        return [str(value).strip() for value in values if str(value).strip()]


class AgentRunDiagnostics(BaseModel):
    failure_kind: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""
    raw_response_truncated: bool = False


class AgentRunFinalization(BaseModel):
    """All durable changes applied when one delegated run terminates."""

    run_status: AgentRunStatus
    completion: AgentCompletion
    evidence: dict[str, Any] = Field(default_factory=dict)
    exit_status: str = ""
    raw_response: str = ""
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    next_status: str = ""
    resumable_status: str = ""
    blocked_reason: str = ""
    commit_hashes: list[str] = Field(default_factory=list)
    handoff_context: str = ""
    handoff_metadata: dict[str, Any] = Field(default_factory=dict)
    comment: str = ""

    @model_validator(mode="after")
    def validate_terminal_status(self) -> "AgentRunFinalization":
        if self.run_status == AgentRunStatus.RUNNING:
            raise ValueError("Agent-run finalization requires a terminal run status.")

        expected_completion_status = (
            AgentCompletionStatus.SUCCESS
            if self.run_status == AgentRunStatus.SUCCESS
            else AgentCompletionStatus.FAILED
        )
        if self.completion.status != expected_completion_status:
            raise ValueError(
                f"Run status {self.run_status.value} requires completion status "
                f"{expected_completion_status.value}."
            )
        return self


class AgentRun(BaseModel):
    id: str
    work_item_id: str
    agent_name: str
    status: AgentRunStatus
    started_at: str = ""
    finished_at: str = ""
    task_description: str = ""
    completion_payload: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    entry_status: str = ""
    exit_status: str = ""
    raw_response: str = ""
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ContextEntry(BaseModel):
    id: str
    work_item_id: str
    author: str
    content: str
    kind: str = "note"
    agent_run_id: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkItemRelationship(BaseModel):
    id: str
    source_work_item_id: str
    target_work_item_id: str
    relationship_type: WorkItemRelationshipType
    created_at: str = ""


class WorkItemStatusHistory(BaseModel):
    id: str
    work_item_id: str
    from_status: str = ""
    to_status: str
    reason: str = ""
    agent_run_id: str = ""
    created_at: str = ""


class WorkItem(BaseModel):
    id: str
    title: str
    description: str
    status: str  # Mapped to WorkItemStatus string values
    type: WorkItemType
    priority: str = "Medium"
    assignees: List[str]
    comments: List[Comment]
    created_at: str = ""
    updated_at: str = ""
    commit_hashes: List[str] = Field(default_factory=list)
    tool_logs: List[ToolLogEntry] = Field(default_factory=list)
    shared_context: str = ""
    target_branch: str = ""
    feature_branch: str = ""
    base_commit: str = ""
    merge_request_id: str = ""
    blocked_reason: str = ""
    resumable_status: str = ""

    # Gate Statuses (Abstracted from custom fields)
    gate_analysis_status: GateStatus = GateStatus.PENDING
    gate_design_status: GateStatus = GateStatus.PENDING
    gate_test_status: GateStatus = GateStatus.PENDING

    # Artifacts
    artifacts: List[ArtifactLink] = Field(default_factory=list)


class WorkItemStore(ABC):
    """
    Abstract interface for persistent work items.

    Work items are ticket-like context records used by agents and workflows.
    """

    @abstractmethod
    def create_work_item(
        self, title: str, description: str, type: WorkItemType, priority: str
    ) -> str:
        """Create a new work item and return its ID."""
        pass

    @abstractmethod
    def get_work_item(self, work_item_id: str) -> WorkItem:
        """Retrieve a standardized work item object."""
        pass

    @abstractmethod
    def search_work_items(self, query: str) -> List[WorkItem]:
        """Search for work items matching a query."""
        pass

    @abstractmethod
    def update_status(self, work_item_id: str, status: WorkItemStatus) -> None:
        """Update the main workflow status of a work item."""
        pass

    @abstractmethod
    def update_description(self, work_item_id: str, description: str) -> None:
        """Update the main description (Markdown)."""
        pass

    @abstractmethod
    def post_comment(self, work_item_id: str, text: str) -> None:
        """Post a comment to the work item."""
        pass

    @abstractmethod
    def set_gate_status(self, work_item_id: str, gate: str, status: GateStatus) -> None:
        """
        Set the status of a specific gate.
        gate: 'analysis', 'design', 'test'
        """
        pass

    @abstractmethod
    def add_artifact_link(
        self,
        work_item_id: str,
        title: str,
        url: str,
        comment: str = None,
        artifact_type: str = "link",
        agent_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a link to an external artifact (file, doc, etc) and optionally post a comment."""
        pass

    @abstractmethod
    def delete_artifact_link(
        self,
        work_item_id: str,
        title: str | None = None,
        url: str | None = None,
    ) -> None:
        """Delete artifact links matching the given title and/or URL."""
        pass

    @abstractmethod
    def remove_comment(self, work_item_id: str, comment_id: str) -> None:
        """Remove a comment from a work item by comment ID."""
        pass

    @abstractmethod
    def add_commit_hash(self, work_item_id: str, commit_hash: str) -> None:
        """Record a git commit hash that is relevant to this work item."""
        pass

    @abstractmethod
    def append_shared_context(
        self,
        work_item_id: str,
        author: str,
        context: str,
        agent_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append shared context for later agents working on this work item."""
        pass

    @abstractmethod
    def add_context_entry(
        self,
        work_item_id: str,
        author: str,
        content: str,
        kind: str = "note",
        agent_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a structured context entry for later agents."""
        pass

    @abstractmethod
    def list_context_entries(
        self, work_item_id: str, limit: int | None = None
    ) -> List[ContextEntry]:
        """List structured context entries for a work item."""
        pass

    @abstractmethod
    def start_agent_run(
        self,
        work_item_id: str,
        agent_name: str,
        task_description: str,
    ) -> str:
        """Create an agent run record and return its ID."""
        pass

    @abstractmethod
    def finish_agent_run(
        self,
        agent_run_id: str,
        status: AgentRunStatus,
        completion_payload: dict[str, Any],
        evidence: dict[str, Any],
        exit_status: str = "",
        raw_response: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        """Mark an agent run complete and store completion/evidence payloads."""
        pass

    @abstractmethod
    def finalize_agent_run(
        self,
        agent_run_id: str,
        finalization: AgentRunFinalization,
    ) -> None:
        """Atomically finalize an agent run and all resulting work-item changes."""
        pass

    @abstractmethod
    def get_running_agent_run(self, work_item_id: str) -> AgentRun | None:
        """Return the currently running agent run for a work item, if any."""
        pass

    @abstractmethod
    def list_agent_runs(self, work_item_id: str) -> List[AgentRun]:
        """List agent runs for a work item."""
        pass

    @abstractmethod
    def add_tool_log(
        self,
        work_item_id: str,
        tool_name: str,
        status: str,
        args: dict[str, Any],
        result: str = "",
    ) -> None:
        """Append an automatic tool execution log entry to this work item."""
        pass

    @abstractmethod
    def update_git_metadata(
        self,
        work_item_id: str,
        target_branch: str | None = None,
        feature_branch: str | None = None,
        base_commit: str | None = None,
        merge_request_id: str | None = None,
    ) -> None:
        """Update git and merge-request metadata for this work item."""
        pass

    @abstractmethod
    def get_blockers(self, work_item_id: str) -> List[str]:
        """Return a list of work item IDs that block this work item."""
        pass

    @abstractmethod
    def add_work_item_relationship(
        self,
        source_work_item_id: str,
        target_work_item_id: str,
        relationship_type: WorkItemRelationshipType,
    ) -> str:
        """Create a typed relationship between two work items."""
        pass

    @abstractmethod
    def list_work_item_relationships(
        self,
        work_item_id: str,
    ) -> List[WorkItemRelationship]:
        """List relationships where the work item is source or target."""
        pass

    @abstractmethod
    def list_status_history(self, work_item_id: str) -> List[WorkItemStatusHistory]:
        """List durable workflow status transitions for a work item."""
        pass

    @abstractmethod
    def list_work_items(self) -> List[WorkItem]:
        """List all work items in the system."""
        pass

    def create_ticket(
        self, title: str, description: str, type: WorkItemType, priority: str
    ) -> str:
        """Backward-compatible alias for create_work_item."""
        return self.create_work_item(title, description, type, priority)

    def get_ticket(self, ticket_id: str) -> WorkItem:
        """Backward-compatible alias for get_work_item."""
        return self.get_work_item(ticket_id)

    def search_tickets(self, query: str) -> List[WorkItem]:
        """Backward-compatible alias for search_work_items."""
        return self.search_work_items(query)

    def list_tickets(self) -> List[WorkItem]:
        """Backward-compatible alias for list_work_items."""
        return self.list_work_items()


# Backwards-compatible names while callers are migrated.
TicketType = WorkItemType
TicketStatus = WorkItemStatus
Ticket = WorkItem
TicketSystem = WorkItemStore
