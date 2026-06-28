import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from src.ariadne.infrastructure.container import DependencyRegistry
from src.ariadne.work_items.models import TicketStatus

def update():
    # Use standard ticket tools
    tools = DependencyRegistry.get_work_item_tools()
    
    comment_text = """Review of previous V-Model execution:
1. **Developer Agent Error**: Traceability tags (Implementation of ARCH-15. Fulfills REQ-15.) were inserted as raw Python code instead of being placed inside docstrings or comments, which broke src/tui/app.py and src/tui/widgets.py with SyntaxErrors.
2. **Tester Agent Omission**: Absolutely no tests were generated for the TUI feature despite the existence of the TEST ticket. 

We are restarting the V-Model process to address these issues.
"""
    
    ticket_id = '15'
    
    try:
        tools.post_comment(ticket_id, comment_text)
        print(f"Successfully added comment to ticket {ticket_id}.")
    except Exception as e:
        print(f"Error adding comment: {e}")

    try:
        # Update status to Backlog using standard enum
        tools.update_status(ticket_id, TicketStatus.BACKLOG.value)
        print(f"Successfully updated ticket {ticket_id} status to Backlog.")
    except Exception as e:
        print(f"Error updating ticket: {e}")

if __name__ == "__main__":
    update()