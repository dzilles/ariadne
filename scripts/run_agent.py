import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from headless_ariadne import HeadlessAriadne
from src.ariadne.infrastructure.container import DependencyRegistry
from src.ariadne.workflows.context import set_active_ticket_id
from src.ariadne.workflows.rules import get_rule_for_status, generate_instructions

def run(agent_name: str, ticket_id: str, instruction: str):
    a = HeadlessAriadne()
    
    set_active_ticket_id(ticket_id)
    
    # Fetch work item status and inject V-Model instructions.
    agent = a.get_agent(agent_name)
    try:
        work_item = DependencyRegistry.get_work_item_tools().system.get_work_item(ticket_id)
        status = work_item.status
        rule = get_rule_for_status(status)
        if rule:
            mission_instr = generate_instructions(rule, ticket_id)
            agent.set_mission_instructions(mission_instr)
            print(f"✅ Injected mission instructions for status: {status}")
    except Exception as e:
        print(f"⚠️ Failed to inject mission instructions: {e}")

    print(f"🚀 Running {agent_name} Agent directly on ticket {ticket_id}...")
    print(f"Instruction: {instruction}")
    response = a.chat_with_pause(agent_name, instruction, max_tool_calls=40)
    
    print(f"\n--- Final {agent_name} Agent Response ---")
    print(response)

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python scripts/run_agent.py <AgentName> <TicketID> <Instruction>")
        sys.exit(1)
        
    run(sys.argv[1], sys.argv[2], sys.argv[3])
