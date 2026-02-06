"""Example integration with LangGraph multi-agent project.

This shows how to connect Ariadne with a LangGraph application,
displaying agent transitions, tool calls, and streaming responses.

Requires: pip install langgraph langchain-anthropic
"""

import asyncio
from typing import Annotated, TypedDict

from ariadne import ChatUI, BotResponse

# LangGraph imports
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_anthropic import ChatAnthropic


# =============================================================================
# Define your tools
# =============================================================================

@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    # Your actual implementation here
    return f"Search results for: {query}\n1. Result one\n2. Result two"


@tool
def read_file(path: str) -> str:
    """Read contents of a file."""
    # Your actual implementation here
    try:
        with open(path) as f:
            return f.read()[:1000]  # Limit output
    except FileNotFoundError:
        return f"File not found: {path}"


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file."""
    # Your actual implementation here
    with open(path, "w") as f:
        f.write(content)
    return f"Written {len(content)} bytes to {path}"


# Collect all tools
tools = [search_web, read_file, write_file]


# =============================================================================
# Define the graph state
# =============================================================================

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    current_agent: str


# =============================================================================
# Create the LangGraph
# =============================================================================

def create_graph():
    """Create the LangGraph multi-agent graph."""

    # Create LLM with tools
    llm = ChatAnthropic(model="claude-sonnet-4-20250514")
    llm_with_tools = llm.bind_tools(tools)

    # Define agent nodes
    def researcher(state: AgentState) -> AgentState:
        """Research agent that gathers information."""
        messages = state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response], "current_agent": "researcher"}

    def writer(state: AgentState) -> AgentState:
        """Writer agent that produces final output."""
        messages = state["messages"]
        response = llm.invoke(messages)
        return {"messages": [response], "current_agent": "writer"}

    # Define routing logic
    def should_continue(state: AgentState) -> str:
        """Determine next step based on last message."""
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "end"

    # Build the graph
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("researcher", researcher)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("writer", writer)

    # Add edges
    graph.add_edge(START, "researcher")
    graph.add_conditional_edges(
        "researcher",
        should_continue,
        {"tools": "tools", "end": "writer"}
    )
    graph.add_edge("tools", "researcher")
    graph.add_edge("writer", END)

    return graph.compile()


# =============================================================================
# Ariadne integration
# =============================================================================

class LangGraphRunner:
    """Runs a LangGraph and streams events to Ariadne."""

    def __init__(self, graph):
        self.graph = graph

    async def run(
        self,
        message: str,
        response: BotResponse,
    ) -> None:
        """Run the graph and stream events to the response."""

        # Initial state
        state = {
            "messages": [HumanMessage(content=message)],
            "current_agent": "",
        }

        current_agent = None

        # Stream events from the graph
        async for event in self.graph.astream_events(state, version="v2"):
            # Check for cancellation
            if response.is_cancelled:
                return

            kind = event["event"]

            # Handle different event types
            if kind == "on_chain_start":
                name = event.get("name", "")
                if name in ("researcher", "writer"):
                    current_agent = name
                    response.set_status(
                        f"Agent: {name.title()}",
                        "Processing..."
                    )

            elif kind == "on_chat_model_stream":
                # Streaming LLM output
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content") and chunk.content:
                    # Update status with streaming content preview
                    content = chunk.content
                    if isinstance(content, str) and content.strip():
                        response.update_status(f"Generating: {content[:50]}...")

            elif kind == "on_tool_start":
                # Tool is starting
                tool_name = event["name"]
                tool_input = event["data"].get("input", {})
                input_preview = str(tool_input)[:50]
                response.tool(tool_name, input_preview)

            elif kind == "on_tool_end":
                # Tool completed - status will be replaced by next action
                pass

            elif kind == "on_tool_error":
                # Tool failed - add persistent error
                tool_name = event["name"]
                error = str(event["data"].get("error", "Unknown error"))
                response.tool_error(tool_name, error)

            elif kind == "on_chain_end":
                name = event.get("name", "")
                if name == "LangGraph":
                    # Graph completed, extract final response
                    output = event["data"].get("output", {})
                    messages = output.get("messages", [])

                    # Find the last AI message
                    final_content = None
                    for msg in reversed(messages):
                        if isinstance(msg, AIMessage) and msg.content:
                            final_content = msg.content
                            break

                    if final_content:
                        response.complete(final_content)
                    else:
                        response.complete("Task completed.")


# =============================================================================
# Main application
# =============================================================================

# Create the graph and runner
graph = create_graph()
runner = LangGraphRunner(graph)

# Create the UI
ui = ChatUI(title="LangGraph Multi-Agent")


@ui.on_message
async def handle_message(message: str, response: BotResponse) -> None:
    """Handle messages using LangGraph."""
    await runner.run(message, response)


if __name__ == "__main__":
    ui.run()
