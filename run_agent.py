import sys
from headless_ariadne import HeadlessAriadne
from src.workflows.context import set_active_ticket_id
from src.workflows.rules import get_rule_for_status, generate_instructions

def run(agent_name: str, ticket_id: str, instruction: str):
    a = HeadlessAriadne()
    
    set_active_ticket_id(ticket_id)
    
    # NEW: Fetch ticket status and inject V-Model instructions
    agent = a.get_agent(agent_name)
    try:
        ticket = a.plane.get_issue_by_number(int(ticket_id))
        if ticket:
            status = ticket.get("state_detail", {}).get("name") or ticket.get("state")
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
        print("Usage: python run_agent.py <AgentName> <TicketID> <Instruction>")
        sys.exit(1)
        
    run(sys.argv[1], sys.argv[2], sys.argv[3])
