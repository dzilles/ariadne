import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from headless_ariadne import HeadlessAriadne
from src.ariadne.workflows.context import set_active_ticket_id

def run():
    a = HeadlessAriadne()
    
    # Manually set context since we are bypassing the Orchestrator
    set_active_ticket_id("16")
    
    # Simple instruction for the Requirements Agent to test its System Prompt
    instruction = "Please update docs/requirements/REQ-15.md according to our latest documentation and tagging standards."
    
    print("🚀 Running Requirements Agent directly...")
    response = a.chat_with_pause('Requirements', instruction, max_tool_calls=10)
    
    print("\n--- Final Requirements Agent Response ---")
    print(response)

if __name__ == "__main__":
    run()
