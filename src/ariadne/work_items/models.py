from abc import ABC, abstractmethod
from enum import Enum
from typing import List

from pydantic import BaseModel


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


class WorkItem(BaseModel):
    id: str
    title: str
    description: str
    status: str  # Mapped to WorkItemStatus string values
    type: WorkItemType
    assignees: List[str]
    comments: List[Comment]
    
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
    def create_ticket(self, title: str, description: str, type: WorkItemType, priority: str) -> str:
        """Create a new work item and return its ID."""
        pass

    @abstractmethod
    def get_ticket(self, ticket_id: str) -> WorkItem:
        """Retrieve a standardized work item object."""
        pass

    @abstractmethod
    def search_tickets(self, query: str) -> List[WorkItem]:
        """Search for work items matching a query."""
        pass

    @abstractmethod
    def update_status(self, ticket_id: str, status: WorkItemStatus) -> None:
        """Update the main workflow status of a work item."""
        pass

    @abstractmethod
    def update_description(self, ticket_id: str, description: str) -> None:
        """Update the main description (Markdown)."""
        pass

    @abstractmethod
    def post_comment(self, ticket_id: str, text: str) -> None:
        """Post a comment to the ticket."""
        pass

    @abstractmethod
    def set_gate_status(self, ticket_id: str, gate: str, status: GateStatus) -> None:
        """
        Set the status of a specific gate.
        gate: 'analysis', 'design', 'test'
        """
        pass

    @abstractmethod
    def add_artifact_link(self, ticket_id: str, title: str, url: str, comment: str = None) -> None:
        """Add a link to an external artifact (file, doc, etc) and optionally post a comment."""
        pass

    @abstractmethod
    def get_blockers(self, ticket_id: str) -> List[str]:
        """Return a list of work item IDs that block this work item."""
        pass

    @abstractmethod
    def list_tickets(self) -> List[WorkItem]:
        """List all work items in the system."""
        pass


# Backwards-compatible names while callers are migrated.
TicketType = WorkItemType
TicketStatus = WorkItemStatus
Ticket = WorkItem
TicketSystem = WorkItemStore
