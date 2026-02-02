import logging
from typing import Optional, List
from src.tools.plane_client import PlaneInteraction

logger = logging.getLogger(__name__)

class ProjectManagementAgentTools:
    """
    General project management tools for AI Agents.
    Currently backed by Plane but designed with a generic interface.
    """
    def __init__(self, client: PlaneInteraction):
        self.client = client

    def create_ticket(self, title: str, description: str, priority: str = "Medium") -> str:
        """
        Creates a new task/ticket in the project management system.
        """
        msg = f"[Tool: create_ticket called for '{title}']"
        print(f"\n{msg}")
        logger.info(msg)
        return self.client.create_issue(title, description, priority)

    def create_sub_task(self, parent_ticket_number: int, title: str, description: str) -> str:
        """
        Creates a new sub-task linked to an existing parent ticket.
        """
        msg = f"[Tool: create_sub_task called for parent #{parent_ticket_number}: '{title}']"
        print(f"\n{msg}")
        logger.info(msg)
        return self.client.create_sub_issue(parent_ticket_number, title, description)

    def delete_ticket(self, ticket_number: int) -> str:
        """
        Deletes a ticket by its number (Sequence ID).
        """
        msg = f"[Tool: delete_ticket called for #{ticket_number}]"
        print(f"\n{msg}")
        logger.info(msg)
        return self.client.delete_issue(ticket_number)

    def update_ticket(self, 
                      ticket_number: int, 
                      title: str = None, 
                      description: str = None, 
                      priority: str = None,
                      state: str = None,
                      assignees: List[str] = None,
                      start_date: str = None,
                      due_date: str = None,
                      parent_ticket_number: int = None,
                      labels: List[str] = None) -> str:
        """
        Updates an existing ticket's properties. Only provide fields that need changing.
        """
        msg = f"[Tool: update_ticket called for #{ticket_number}]"
        print(f"\n{msg}")
        logger.info(msg)
        return self.client.update_issue(
            ticket_number, title, description, priority, state, 
            assignees, start_date, due_date, parent_ticket_number, labels
        )

    def search_tickets(self, 
                       keyword: str = None,
                       state_group: str = None, 
                       priority: str = None,
                       assignees: List[str] = None,
                       labels: List[str] = None,
                       state: str = None) -> str:
        """
        Searches for tickets with various filters.
        """
        msg = f"[Tool: search_tickets called with keyword='{keyword}']"
        print(f"\n{msg}")
        logger.info(msg)
        tickets = self.client.list_issues(
            state_group=state_group,
            search_query=keyword,
            priority=priority,
            assignees=assignees,
            labels=labels,
            state=state
        )
        
        if not tickets:
            return "No tickets found matching criteria."
            
        return "\n".join([
            f"#{t['number']} - {t['title']} "
            f"[{t['status']}] "
            f"({t['priority']}) "
            f"Assignees: {', '.join(t['assignees']) if t['assignees'] else 'None'}"
            for t in tickets
        ])

    def get_ticket_details(self, ticket_number: int) -> str:
        """
        Gets the full details of a specific ticket by its number (Sequence ID).
        """
        msg = f"[Tool: get_ticket_details called for #{ticket_number}]"
        print(f"\n{msg}")
        logger.info(msg)
        ticket = self.client.get_issue_by_number(ticket_number)
        if isinstance(ticket, str): return ticket
        if not ticket: return f"Ticket {ticket_number} not found."
             
        issue_id = ticket.get('id')
        links = self.client.get_issue_links(issue_id)
        relations = self.client.get_issue_relations(issue_id)
        comments = self.client.get_comments(ticket_number)

        # Robust assignee parsing
        assignees = []
        for m in ticket.get('assignees', []):
            if isinstance(m, dict):
                name = m.get('member', {}).get('display_name') or m.get('member', {}).get('first_name') or "Unknown"
                assignees.append(name)
            elif isinstance(m, str):
                assignees.append(m) # ID

        # Robust label parsing
        labels = []
        for l in ticket.get('labels', []):
            if isinstance(l, dict):
                labels.append(l.get('name', 'Unknown'))
            elif isinstance(l, str):
                labels.append(l) # ID

        # Format comments
        formatted_comments = "None"
        if isinstance(comments, list) and comments:
            comment_lines = []
            for c in comments:
                actor = c.get('actor_detail', {}).get('display_name', 'Unknown')
                html = c.get('comment_html') or ''
                content = html.replace('<p>', '').replace('</p>', '')
                cid = c.get('id', 'Unknown')
                comment_lines.append(f"- [ID: {cid}] {actor}: {content}")
            formatted_comments = "\n".join(comment_lines)

        # Format for agent consumption
        details = f"""
ID: {ticket.get('sequence_id')}
Title: {ticket.get('name')}
Status: {ticket.get('state_detail', {}).get('name') or ticket.get('state')}
Priority: {ticket.get('priority')}
Assignees: {', '.join(assignees)}
Labels: {', '.join(labels)}
Start Date: {ticket.get('start_date')}
Due Date: {ticket.get('target_date')}
Parent: {ticket.get('parent_detail', {}).get('sequence_id') if ticket.get('parent_detail') else 'None'}

Links:
{chr(10).join([f"- {l.get('title')}: {l.get('url')}" for l in links]) if links else "None"}

Relations:
{chr(10).join([f"- {(r.get('relation') or 'unknown').replace('_', ' ').capitalize()}: #{r.get('related_issue_detail', {}).get('sequence_id') if r.get('related_issue_detail') else 'Unknown'}" for r in relations]) if relations else "None"}

Comments:
{formatted_comments}

Description:
{ticket.get('description_html') or ticket.get('description')}
"""
        return details.strip()

    def add_link(self, ticket_number: int, url: str, title: str = None) -> str:
        """Adds an external link (URL) to a ticket."""
        msg = f"[Tool: add_link called for #{ticket_number}: {url}]"
        print(f"\n{msg}")
        logger.info(msg)
        return self.client.add_issue_link(ticket_number, url, title)

    def add_relation(self, ticket_number: int, related_ticket_number: int, relation_type: str = "relates_to") -> str:
        """
        Adds a relation between two tickets (e.g., blocking, relates_to).
        """
        msg = f"[Tool: add_relation called: #{ticket_number} {relation_type} #{related_ticket_number}]"
        print(f"\n{msg}")
        logger.info(msg)
        return self.client.add_issue_relation(ticket_number, related_ticket_number, relation_type)

    def attach_file(self, ticket_number: int, file_path: str) -> str:
        """Uploads a file attachment to a ticket from a local file path."""
        msg = f"[Tool: attach_file called for #{ticket_number}: {file_path}]"
        print(f"\n{msg}")
        logger.info(msg)
        return self.client.upload_attachment(ticket_number, file_path)

    def add_comment(self, ticket_number: int, comment: str) -> str:
        """Adds a comment/note to a specific ticket."""
        msg = f"[Tool: add_comment called for #{ticket_number}]"
        print(f"\n{msg}")
        logger.info(msg)
        return self.client.add_comment(ticket_number, comment)

    def get_comment_link(self, ticket_number: int, comment_id: str) -> str:
        """Returns a permanent web link to a specific comment."""
        msg = f"[Tool: get_comment_link called for #{ticket_number}, comment {comment_id}]"
        print(f"\n{msg}")
        logger.info(msg)
        return self.client.get_comment_url(ticket_number, comment_id)

    def get_tool_descriptions(self) -> str:
        return """
### Project Management Tools (Plane)
*   `get_ticket_details(ticket_number)`: Reads full details (Story, AC, Comments, Links).
*   `update_ticket(ticket_number, ...)`: Updates status, priority, description, etc.
*   `add_comment(ticket_number, comment)`: Posts a comment.
*   `create_ticket(title, description)`: Creates a new ticket.
*   `add_link(ticket_number, url)`: Adds an external URL link.
*   `add_relation(ticket, related_ticket, type)`: Links tickets (e.g., 'blocking', 'relates_to').
*   `search_tickets(keyword, ...)`: Finds tickets.
"""

