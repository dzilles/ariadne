from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, List

from pydantic import BaseModel, Field


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
    title: str
    url: str

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


class WorkItem(BaseModel):
    id: str
    title: str
    description: str
    status: str  # Mapped to WorkItemStatus string values
    type: WorkItemType
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
    
    # Gate Statuses (Abstracted from custom fields)
    gate_analysis_status: GateStatus = GateStatus.PENDING
    gate_design_status: GateStatus = GateStatus.PENDING
    gate_test_status: GateStatus = GateStatus.PENDING
    
    # Artifacts
    artifacts: List[ArtifactLink] = []


class WorkItemStore(ABC):
    """
    Abstract interface for persistent work items.

    Work items are ticket-like context records used by agents and workflows.
    """

    @abstractmethod
    def create_work_item(self, title: str, description: str, type: WorkItemType, priority: str) -> str:
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
    def add_artifact_link(self, work_item_id: str, title: str, url: str, comment: str = None) -> None:
        """Add a link to an external artifact (file, doc, etc) and optionally post a comment."""
        pass

    @abstractmethod
    def add_commit_hash(self, work_item_id: str, commit_hash: str) -> None:
        """Record a git commit hash that is relevant to this work item."""
        pass

    @abstractmethod
    def append_shared_context(self, work_item_id: str, author: str, context: str) -> None:
        """Append shared context for later agents working on this work item."""
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
    def list_work_items(self) -> List[WorkItem]:
        """List all work items in the system."""
        pass

    def create_ticket(self, title: str, description: str, type: WorkItemType, priority: str) -> str:
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
