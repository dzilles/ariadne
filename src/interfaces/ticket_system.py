from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from enum import Enum

class TicketType(str, Enum):
    FEATURE = "Feature"
    BUG = "Bug"
    TASK = "Task"

class TicketStatus(str, Enum):
    BACKLOG = "Backlog"
    READY_FOR_ANALYSIS = "Ready for Analysis"
    READY_FOR_DESIGN = "Ready for Design"
    READY_FOR_DEVELOPMENT = "Ready for Development"
    READY_FOR_TESTING = "Ready for Testing"
    READY_FOR_QA = "Ready for QA"
    DONE = "Done"

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

class Ticket(BaseModel):
    id: str
    title: str
    description: str
    status: str  # Mapped to TicketStatus string values
    type: TicketType
    assignees: List[str]
    comments: List[Comment]
    
    # Gate Statuses (Abstracted from custom fields)
    gate_analysis_status: GateStatus = GateStatus.PENDING
    gate_design_status: GateStatus = GateStatus.PENDING
    gate_test_status: GateStatus = GateStatus.PENDING
    
    # Artifacts
    artifacts: List[ArtifactLink] = []

class TicketSystem(ABC):
    """
    Abstract Interface for Ticket Management Systems (Plane, Jira, etc.)
    """

    @abstractmethod
    def create_ticket(self, title: str, description: str, type: TicketType, priority: str) -> str:
        """Create a new ticket and return its ID."""
        pass

    @abstractmethod
    def get_ticket(self, ticket_id: str) -> Ticket:
        """Retrieve a standardized Ticket object."""
        pass

    @abstractmethod
    def search_tickets(self, query: str) -> List[Ticket]:
        """Search for tickets matching a query."""
        pass

    @abstractmethod
    def update_status(self, ticket_id: str, status: TicketStatus) -> None:
        """Update the main workflow status of a ticket."""
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
    def add_artifact_link(self, ticket_id: str, title: str, url: str) -> None:
        """Add a link to an external artifact (file, doc, etc)."""
        pass
