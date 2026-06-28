import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from headless_ariadne import HeadlessAriadne
from src.ariadne.workflows.context import set_active_ticket_id

def run():
    a = HeadlessAriadne()
    
    # We are bypassing Orchestrator and giving instructions directly to the Architect Agent
    # just as we did for the Requirements Agent to test its specific system prompt.
    
    instruction = """
    Please update the architecture document for Epic #15 (Terminal User Interface & Human-in-the-loop).
    
    The requirements document is docs/requirements/REQ-15.md.
    The existing design document you need to update is docs/design/ARCH-15.md. 
    
    CRITICAL INSTRUCTIONS:
    1. Update ARCH-15.md based on the latest requirements (specifically the testability hooks FR-13 to FR-17).
    2. Follow the 'FORMAL ARCH-*.MD TEMPLATE' completely. Ensure you include the 'Traceability' header block at the top.
    3. In 'Component Design / Data Models' or 'Integration Points', use the `[PENDING LINK]` tag if you refer to external components that don't have an architecture yet (e.g. Core Engine, Agent Toolsets).
    4. Attach the updated document to Ticket #19 using `add_link`.
    5. After committing your changes, approve the 'design' gate and move the ticket to 'Ready for Development'.
    """
    
    set_active_ticket_id("19")
    
    print("🚀 Starting Architect Agent directly...")
    response = a.chat_with_pause('Architect', instruction, max_tool_calls=15)
    
    print("\n--- Final Architect Agent Response (Paused) ---")
    print(response)

if __name__ == "__main__":
    run()

