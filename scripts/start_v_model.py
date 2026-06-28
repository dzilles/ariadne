import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from headless_ariadne import HeadlessAriadne
from src.ariadne.workflows.context import set_active_ticket_id

def run():
    a = HeadlessAriadne()
    
    instruction = """
    Epic #15 (Terminal User Interface & Human-in-the-loop) has been reopened because the previous run had two major issues:
    1. The Developer Agent caused syntax errors by pasting traceability tags directly into code instead of docstrings.
    2. The Tester Agent produced no tests at all for the TUI. 
    
    You have been updated with a new tool (run_shell_command) and instructions to verify code syntax. 
    
    Please restart the V-model process for Epic #15. Start by delegating to the Requirements Agent to review and refine the requirements if necessary, then proceed through the pipeline.
    """
    
    # Ticket #15 is the Epic. Orchestrator should look at it and its children.
    set_active_ticket_id("15")
    
    # We use chat_with_pause to allow for manual inspection after 10 tool calls.
    print("🚀 Starting Orchestrator for Epic #15...")
    response = a.chat_with_pause('Orchestrator', instruction, max_tool_calls=10)
    
    print("\n--- Final Orchestrator Response (Paused) ---")
    print(response)

if __name__ == "__main__":
    run()

