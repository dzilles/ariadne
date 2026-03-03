import os
import sys
import logging

# Ensure src is in path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.interfaces.plane_adapter import PlaneTicketSystem
from src.interfaces.ticket_system import TicketStatus
from src.workflows.context import set_active_ticket_id
from src.agents.requirements_agent import RequirementsAgent

logging.basicConfig(level=logging.INFO)

def run_test():
    print("Initializing Plane Ticket System...")
    try:
        ts = PlaneTicketSystem()
        print(f"DEBUG: Plane API URL: {ts.client.base_url}")
        print(f"DEBUG: Plane API Token: {ts.client.api_key[:5]}...")
    except Exception as e:
        print(f"Failed to init PlaneTicketSystem: {e}")
        return

    print("Creating a dummy ticket...")
    # create_ticket(title, description, type, priority)
    from src.interfaces.ticket_system import TicketType
    try:
        issue_id = ts.create_ticket(
            title="Test Requirements Agent",
            description="As a user, I want a dummy feature to test the agent so I can verify its tools.",
            type=TicketType.FEATURE,
            priority="low"
        )
        print(f"Created Issue. ID string returned: {issue_id}")
    except Exception as e:
        print(f"Failed to create ticket: {e}")
        return

    # Check if we can parse the integer out of the message or use it directly
    ticket_id = None
    import re
    match = re.search(r"Ticket (\d+)", issue_id)
    if match:
        ticket_id = match.group(1)
    else:
        # If it returned just an ID
        ticket_id = issue_id.strip()

    print(f"Parsed Ticket ID: {ticket_id}")
    
    if not ticket_id or not ticket_id.isdigit():
        print(f"Failed to parse a valid numeric ticket ID from: {issue_id}")
        return
        
    print(f"Moving ticket {ticket_id} to Ready for Analysis...")
    try:
        ts.update_status(ticket_id, TicketStatus.READY_FOR_ANALYSIS)
    except Exception as e:
        print(f"Failed to move ticket to Ready for Analysis: {e}")
        # we try to continue anyway

    print(f"Setting Context Active Ticket ID to {ticket_id}...")
    set_active_ticket_id(ticket_id)

    print("Initializing RequirementsAgent...")
    try:
        agent = RequirementsAgent()
    except Exception as e:
        print(f"Failed to init RequirementsAgent: {e}")
        return

    print("Sending message to agent...")
    prompt = (
        "Please read the active ticket. Generate a requirement doc for it "
        "and update its status to Ready for Design."
    )
    
    response = agent.chat(prompt)
    print("\n--- Agent Response ---")
    print(response)
    print("----------------------\n")
    
    # Check status
    try:
        updated_ticket = ts.get_ticket(ticket_id)
        print(f"Final Ticket Status in Plane: {updated_ticket.status.value}")
        print(f"Comments on ticket: {len(updated_ticket.comments)}")
        print(f"Artifacts linked: {len(updated_ticket.artifacts)}")
    except Exception as e:
        print(f"Failed to get updated ticket: {e}")

if __name__ == "__main__":
    run_test()
