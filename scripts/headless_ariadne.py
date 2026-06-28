"""
Ariadne Headless Testing Interface & Workflow Guide

This script allows interacting with Ariadne agents directly from the CLI, bypassing 
the TUI. It is designed for LLM-to-LLM collaboration where one agent (you) tests 
the specialized V-Model agents.

--- WORKFLOW: STEP-LIMITED SURGICAL TESTING ---

1. INITIALIZATION:
   - Always initialize the interface first:
     ariadne = HeadlessAriadne()

2. SURGICAL DELEGATION (Prompting):
   - Do NOT give vague instructions. Use this format for the 'message' argument:
     Goal: [Clear statement of the desired outcome]
     Knowledge Summary: [What we already know from comments or previous steps]
     Reference Manifest: [EXACT files/folders the agent should examine]
     Expected Artifact: [File path and format to be produced]

3. JIT CONTEXT MANAGEMENT:
   - Mutating tools (write_file, commit) are BLOCKED unless a context is set.
   - Manually set the context before calling the agent:
     from src.ariadne.workflows.context import set_active_ticket_id
     set_active_ticket_id('1')

4. STEP-LIMITED EXECUTION:
   - Use 'chat_with_pause' to prevent agents from over-analyzing and wasting tokens.
   - Recommended limit: 5-10 tool calls.
     ariadne.chat_with_pause('Developer', instruction, max_tool_calls=5)
   - After the pause, review the logs/files and decide whether to resume or adjust.

5. TICKET STATE SYNCHRONIZATION:
   - If an agent is blocked by the JIT Guard, ensure the ticket is in the correct state.
"""

import asyncio
import logging
import sys
import os
from typing import Any, Dict, List

# Add project root to path
sys.path.append(os.getcwd())

from src.ariadne.ui.agent_adapter import AGENT_CLASSES
from src.ariadne.infrastructure.container import DependencyRegistry
from src.ariadne.config.settings import settings
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

# Setup logging to file to keep console clean
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='logs/headless_test.log',
    filemode='w'
)
logger = logging.getLogger("HeadlessAriadne")

class HeadlessAriadne:
    def __init__(self):
        self.agents = {}
        try:
            self.ticket_tools = DependencyRegistry.get_work_item_tools()
            print(f"✅ Ticket system initialized: {DependencyRegistry.get_sqlite_ticket_system().db_path}")
        except Exception as e:
            print(f"❌ Failed to initialize ticket system: {e}")

    def get_agent(self, name: str):
        if name not in self.agents:
            if name in AGENT_CLASSES:
                print(f"🔄 Initializing {name} agent...")
                self.agents[name] = AGENT_CLASSES[name]()
            else:
                raise ValueError(f"Unknown agent: {name}")
        return self.agents[name]

    def chat_with_pause(self, agent_name: str, message: str, max_tool_calls: int = 5) -> str:
        """
        Runs the agent but pauses after a certain number of tool calls.
        """
        agent = self.get_agent(agent_name)
        print(f"💬 [You -> {agent_name}]: {message}")
        
        # Add user message to history
        agent.chat_history.append(HumanMessage(content=message))
        
        inputs = {"messages": agent.chat_history}
        tool_call_count = 0
        final_response = "[No final response yet - paused for review]"

        print(f"🚀 Running {agent_name} (Max {max_tool_calls} tool calls before pause)...")
        
        try:
            # Use stream to intercept steps
            for chunk in agent.agent_executor.stream(inputs, config={"recursion_limit": 50}):
                # Check for tool calls and thoughts in the chunk
                if "agent" in chunk:
                    node_data = chunk["agent"]
                    if "messages" in node_data:
                        msg = node_data["messages"][0]
                        
                        # Capture and print Thoughts/Reasoning
                        if hasattr(msg, 'content') and msg.content:
                            content = msg.content
                            if isinstance(content, list):
                                text = "".join([p.get("text", "") for p in content if isinstance(p, dict)])
                            else:
                                text = str(content)
                            
                            if text.strip():
                                print(f"\n🧠 [Thought]:\n{text.strip()}\n")

                        # Handle Tool Calls
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            for tc in msg.tool_calls:
                                tool_call_count += 1
                                print(f"🛠️  [Tool Call {tool_call_count}/{max_tool_calls}]: {tc['name']}({tc['args']})")
                
                # Check for tool outputs
                if "tools" in chunk:
                    for msg in chunk["tools"]["messages"]:
                        # Truncate output for display
                        content = str(msg.content)
                        display_content = (content[:100] + '...') if len(content) > 100 else content
                        print(f"📥 [Tool Output]: {display_content}")

                # Update history with the new messages
                for node_name, data in chunk.items():
                    if "messages" in data:
                        for m in data["messages"]:
                            # Avoid duplicates by checking message ID
                            if not any(hasattr(hm, 'id') and hasattr(m, 'id') and hm.id == m.id for hm in agent.chat_history):
                                agent.chat_history.append(m)

                # Pause only AFTER the 'tools' node has provided output for the 'agent' call
                if tool_call_count >= max_tool_calls and "tools" in chunk:
                    print(f"\n⚠️  PAUSE: Reached {max_tool_calls} tool calls and executed them. Stopping for review.")
                    return f"[PAUSED after {tool_call_count} tool calls. Last history item: {agent.chat_history[-1].content[:100] if agent.chat_history else 'None'}]"

            # If we finish without hitting the limit
            last_msg = agent.chat_history[-1]
            final_response = last_msg.content
            print(f"🤖 [{agent_name}]: {final_response}")
            return final_response

        except Exception as e:
            error_msg = f"[System Error: {str(e)}]"
            agent.chat_history.append(AIMessage(content=error_msg))
            print(f"❌ {error_msg}")
            return error_msg

    def get_ticket_details(self, number: str):
        try:
            details = self.ticket_tools.get_work_item(number)
            print(details)
            return details
        except Exception as e:
            print(f"Error getting ticket #{number}: {e}")
            return None

    def list_tickets(self):
        try:
            tickets = self.ticket_tools.system.list_tickets()
            print(f"\n--- Current Tickets ({len(tickets)}) ---")
            for t in tickets:
                print(f"#{t.id} [{t.status}] {t.title} (Assignees: {', '.join(t.assignees)})")
            print("---------------------------\n")
            return tickets
        except Exception as e:
            print(f"Error listing tickets: {e}")
            return []

def main():
    ariadne = HeadlessAriadne()
    # Script is designed to be used via 'python3 -c' or imported in an interactive session

if __name__ == "__main__":
    main()