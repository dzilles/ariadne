from typing import List, Optional
from src.interfaces.ticket_system import (
    TicketSystem, 
    Ticket, 
    TicketStatus, 
    TicketType, 
    GateStatus, 
    Comment, 
    ArtifactLink
)
from src.tools.plane_client import PlaneInteraction

class PlaneTicketSystem(TicketSystem):
    """
    Concrete implementation of TicketSystem for Plane.
    Wraps the existing PlaneInteraction class.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.client = PlaneInteraction(api_key=api_key)

    def _map_plane_state_to_status(self, plane_state: str) -> TicketStatus:
        """Maps Plane state names to standardized TicketStatus."""
        # Simple string matching for now. 
        # In a real setup, this might query a configuration mapping.
        status_map = {
            "Backlog": TicketStatus.BACKLOG,
            "Ready for Analysis": TicketStatus.READY_FOR_ANALYSIS,
            "Ready for Design": TicketStatus.READY_FOR_DESIGN,
            "Ready for Development": TicketStatus.READY_FOR_DEVELOPMENT,
            "Ready for Testing": TicketStatus.READY_FOR_TESTING,
            "Ready for QA": TicketStatus.READY_FOR_QA,
            "Done": TicketStatus.DONE
        }
        return status_map.get(plane_state, TicketStatus.BACKLOG) # Default to Backlog if unknown

    def _map_status_to_plane_state(self, status: TicketStatus) -> str:
        """Maps standardized TicketStatus to Plane state names."""
        return status.value

    def create_ticket(self, title: str, description: str, type: TicketType, priority: str) -> str:
        # Plane client returns a formatted string like "Success: Created Ticket 25 ..."
        # We need to extract the ID, but for now we rely on the client's return or parse it.
        # The base client returns a string message. Ideally it should return the ID.
        # For this adapter, we will call the client and try to return the sequence ID.
        result = self.client.create_issue(title, description, priority, type.value)
        # Parse "Success: Created Ticket 12 ..."
        try:
            import re
            match = re.search(r"Ticket (\d+)", result)
            if match:
                return match.group(1)
            return result # Fallback
        except Exception:
            return result

    def get_ticket(self, ticket_id: str) -> Ticket:
        """
        Retrieve a ticket by its Sequence ID (e.g., "25").
        """
        try:
            # Plane client uses int for sequence_id
            seq_id = int(ticket_id)
            issue_data = self.client.get_issue_by_number(seq_id)
            
            if not issue_data:
                raise ValueError(f"Ticket {ticket_id} not found.")

            # Fetch Comments
            raw_comments = self.client.get_comments(seq_id)
            comments = []
            for c in raw_comments:
                if isinstance(c, dict):
                    comments.append(Comment(
                        id=c.get("id"),
                        text=c.get("comment_html", "").replace("<p>", "").replace("</p>", ""), # Strip basic HTML
                        author=c.get("actor_detail", {}).get("display_name", "Unknown"),
                        created_at=c.get("created_at")
                    ))

            # Fetch Links (Artifacts)
            raw_links = self.client.get_issue_links(issue_data.get("id"))
            artifacts = []
            for l in raw_links:
                if isinstance(l, dict):
                    artifacts.append(ArtifactLink(
                        title=l.get("title", "Link"),
                        url=l.get("url")
                    ))

            # Map Status
            current_state = issue_data.get("state_detail", {}).get("name")
            status = self._map_plane_state_to_status(current_state)

            # Safely process assignees
            assignees_list = []
            for m in issue_data.get("assignees", []):
                if isinstance(m, dict):
                    assignees_list.append(m.get("member", {}).get("display_name", "Unknown"))
                elif isinstance(m, str):
                    assignees_list.append(m)

            return Ticket(
                id=str(issue_data.get("sequence_id")),
                title=issue_data.get("name"),
                description=issue_data.get("description_html", "").replace("<p>", "").replace("</p>", ""), # Strip basic HTML
                status=status,
                type=TicketType.FEATURE, # Defaulting for now, ideally parsed from label or type field
                assignees=assignees_list,
                comments=comments,
                artifacts=artifacts
                # Gate statuses would need to be fetched from Custom Properties (not yet implemented in base client)
            )
        except ValueError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to fetch ticket {ticket_id}: {e}")

    def search_tickets(self, query: str) -> List[Ticket]:
        # Basic implementation using the list_issues method
        raw_issues = self.client.list_issues(search_query=query)
        tickets = []
        for issue in raw_issues:
            # list_issues returns simplified dicts, so we convert them 
            # Note: This is a partial conversion, get_ticket does a full fetch
            tickets.append(Ticket(
                id=str(issue.get("number")),
                title=issue.get("title"),
                description="",
                status=self._map_plane_state_to_status(issue.get("status")),
                type=TicketType.FEATURE,
                assignees=issue.get("assignees"),
                comments=[]
            ))
        return tickets

    def update_status(self, ticket_id: str, status: TicketStatus) -> None:
        plane_state = self._map_status_to_plane_state(status)
        self.client.update_issue_status(int(ticket_id), plane_state)

    def update_description(self, ticket_id: str, description: str) -> None:
        self.client.update_issue(int(ticket_id), description=description)

    def post_comment(self, ticket_id: str, text: str) -> None:
        self.client.add_comment(int(ticket_id), text)

    def set_gate_status(self, ticket_id: str, gate: str, status: GateStatus) -> None:
        # TODO: Implement Custom Property update in PlaneInteraction
        # For now, we will post a comment as a fallback
        comment = f"**GATE UPDATE**: {gate.upper()} set to {status.value}"
        self.post_comment(ticket_id, comment)

    def add_artifact_link(self, ticket_id: str, title: str, url: str) -> None:
        self.client.add_issue_link(int(ticket_id), url, title)
