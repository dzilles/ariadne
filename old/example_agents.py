"""Example showing agent selection functionality."""

import asyncio
from ariadne import ChatUI, BotResponse, Agent


# Define some example agents
agents = [
    Agent(
        name="researcher",
        description="Searches the web and analyzes information",
        metadata={"tools": ["web_search", "read_page"]},
    ),
    Agent(
        name="coder",
        description="Writes and reviews code",
        metadata={"tools": ["write_file", "run_code"]},
    ),
    Agent(
        name="analyst",
        description="Analyzes data and creates reports",
        metadata={"tools": ["query_db", "create_chart"]},
    ),
]

ui = ChatUI(title="Multi-Agent Chat", agents=agents)


@ui.on_agent_change
def handle_agent_change(agent: Agent | None) -> None:
    """Called when the active agent changes."""
    if agent:
        print(f"Switched to agent: {agent.name}")
    else:
        print("No agent selected")


@ui.on_message
async def handle_message(message: str, response: BotResponse) -> None:
    """Handle messages with the active agent."""
    agent = ui.get_active_agent()

    if not agent:
        response.error("No agent selected. Use `/agent <name>` to select one.")
        return

    # Show which agent is handling the request
    response.thinking(f"{agent.name} is processing your request...")
    await asyncio.sleep(0.5)

    # Simulate agent-specific tool usage
    if agent.metadata and "tools" in agent.metadata:
        for tool in agent.metadata["tools"]:
            response.tool(tool, f"executing for: {message[:30]}...")
            await asyncio.sleep(0.3)

    # Generate response based on agent type
    if agent.name == "researcher":
        response.complete(
            f"**Research Results**\n\n"
            f"Based on my search for *{message}*, I found:\n\n"
            f"1. First relevant finding\n"
            f"2. Second relevant finding\n"
            f"3. Third relevant finding\n\n"
            f"Would you like me to dig deeper into any of these?"
        )
    elif agent.name == "coder":
        response.complete(
            f"**Code Analysis**\n\n"
            f"Here's what I can do for *{message}*:\n\n"
            f"```python\n"
            f"def solution():\n"
            f"    # Implementation here\n"
            f"    pass\n"
            f"```\n\n"
            f"Want me to implement this?"
        )
    elif agent.name == "analyst":
        response.complete(
            f"**Analysis Report**\n\n"
            f"For *{message}*, here's my analysis:\n\n"
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| Score  | 85%   |\n"
            f"| Trend  | Up    |\n\n"
            f"Need more detailed analysis?"
        )
    else:
        response.complete(f"Agent {agent.name} processed: {message}")


if __name__ == "__main__":
    print("Available commands:")
    print("  /agent        - List available agents")
    print("  /agent <name> - Switch to an agent")
    print("  /help         - Show all commands")
    print()
    ui.run()
