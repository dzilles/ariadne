from headless_ariadne import HeadlessAriadne
from src.tools.pm_tools import ProjectManagementAgentTools

def update():
    a = HeadlessAriadne()
    pm = ProjectManagementAgentTools(a.plane)
    
    comment_text = """Review of previous V-Model execution:
1. **Developer Agent Error**: Traceability tags (Implementation of ARCH-15. Fulfills REQ-15.) were inserted as raw Python code instead of being placed inside docstrings or comments, which broke src/tui/app.py and src/tui/widgets.py with SyntaxErrors.
2. **Tester Agent Omission**: Absolutely no tests were generated for the TUI feature despite the existence of the TEST ticket. tests/unit/ only contains tests for plane_client.py.

We are restarting the V-Model process to address these issues.
"""
    
    try:
        # pm.add_comment was already called successfully in the previous step
        pass
    except Exception as e:
        print(f"Error adding comment: {e}")

    try:
        # Need to use the proper Plane state UUID or name
        # The list output showed:
        # #15 [94cff056-be45-4103-b15c-ac9b498b2204] Epic: Terminal User Interface & Human-in-the-loop (Assignees: )
        # Status might need to be resolved.
        pm.update_ticket(ticket_number='15', state='Todo')
        print("Successfully updated ticket 15 state to Todo.")
    except Exception as e:
        print(f"Error updating ticket: {e}")
        try:
            pm.update_ticket(ticket_number='15', state='Backlog')
            print("Successfully updated ticket 15 state to Backlog.")
        except Exception as e2:
            print(f"Error updating ticket to Backlog: {e2}")

if __name__ == "__main__":
    update()
