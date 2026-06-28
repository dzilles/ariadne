import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from headless_ariadne import HeadlessAriadne
from src.ariadne.workflows.context import set_active_ticket_id

def run():
    a = HeadlessAriadne()
    
    # Very simple instruction to test if the System Prompt handles the details
    instruction = "Please delegate Ticket #16 to the Requirements Agent to update docs/requirements/REQ-15.md according to our latest documentation and tagging standards."
    
    set_active_ticket_id("15")
    
    print("🚀 Starting Orchestrator with a simple instruction...")
    response = a.chat_with_pause('Orchestrator', instruction, max_tool_calls=15)
    
    print("\n--- Final Orchestrator Response (Paused) ---")
    print(response)

if __name__ == "__main__":
    run()
