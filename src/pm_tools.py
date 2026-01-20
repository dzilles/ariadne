from typing import Optional, List
from src.plane_client import PlaneInteraction

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
        
        Args:
            title: The short and clear title of the ticket.
            description: The full HTML description including User Story and Acceptance Criteria.
            priority: The priority level (Low, Medium, High, Urgent). Defaults to Medium.
        """
        print(f"\n[Tool: create_ticket called for '{title}']")
        return self.client.create_issue(title, description, priority)

    def create_sub_task(self, parent_ticket_number: int, title: str, description: str) -> str:
        """
        Creates a new sub-task linked to an existing parent ticket.
        
        Args:
            parent_ticket_number: The integer Sequence ID of the parent ticket (e.g., 12).
            title: The short title of the sub-task.
            description: The description of the task.
        """
        print(f"\n[Tool: create_sub_task called for parent #{parent_ticket_number}: '{title}']")
        return self.client.create_sub_issue(parent_ticket_number, title, description)

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
        
        Args:
            ticket_number: Sequence ID of the ticket.
            title: (Optional) New title.
            description: (Optional) New HTML description.
            priority: (Optional) New priority (low, medium, high, urgent).
            state: (Optional) New state name (e.g., "In Progress").
            assignees: (Optional) List of names or emails to assign.
            start_date: (Optional) Start date in YYYY-MM-DD format.
            due_date: (Optional) Due date in YYYY-MM-DD format.
            parent_ticket_number: (Optional) Sequence ID of the new parent.
            labels: (Optional) List of label names.
        """
        print(f"\n[Tool: update_ticket called for #{ticket_number}]")
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
        
        Args:
            keyword: Text to search for in title/description.
            state_group: Filter by 'backlog', 'started', 'completed', 'cancelled'.
            priority: Filter by 'low', 'medium', 'high', 'urgent'.
            assignees: List of names or emails.
            labels: List of label names.
            state: Specific state name (e.g., "Todo", "In Progress").
        """
        print(f"\n[Tool: search_tickets called with keyword='{keyword}']")
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
        Use this to read all properties including status, assignees, dates, links, and relations.
        """
        print(f"\n[Tool: get_ticket_details called for #{ticket_number}]")
        ticket = self.client.get_issue_by_number(ticket_number)
        if isinstance(ticket, str): return ticket
        if not ticket: return f"Ticket {ticket_number} not found."
             
        issue_id = ticket.get('id')
        links = self.client.get_issue_links(issue_id)
        relations = self.client.get_issue_relations(issue_id)

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
{chr(10).join([f"- {r.get('relation').replace('_', ' ').capitalize()}: #{r.get('related_issue_detail', {}).get('sequence_id')}" for r in relations]) if relations else "None"}

Description:
{ticket.get('description_html') or ticket.get('description')}
"""
        return details.strip()

    def add_link(self, ticket_number: int, url: str, title: str = None) -> str:
        """Adds an external link (URL) to a ticket."""
        print(f"\n[Tool: add_link called for #{ticket_number}: {url}]")
        return self.client.add_issue_link(ticket_number, url, title)

    def add_relation(self, ticket_number: int, related_ticket_number: int, relation_type: str = "related") -> str:
        """
        Adds a relation between two tickets (e.g., blocking, related).
        Relation types: 'related', 'blocking', 'blocked_by', 'duplicate'.
        """
        print(f"\n[Tool: add_relation called: #{ticket_number} {relation_type} #{related_ticket_number}]")
        return self.client.add_issue_relation(ticket_number, related_ticket_number, relation_type)

    def attach_file(self, ticket_number: int, file_path: str) -> str:
        """Uploads a file attachment to a ticket from a local file path."""
        print(f"\n[Tool: attach_file called for #{ticket_number}: {file_path}]")
        return self.client.upload_attachment(ticket_number, file_path)

    def add_comment(self, ticket_number: int, comment: str) -> str:
        """Adds a comment/note to a specific ticket."""
        print(f"\n[Tool: add_comment called for #{ticket_number}]")
        return self.client.add_comment(ticket_number, comment)

