"""LangGraph adapter for Ariadne.

Provides utilities to connect LangGraph applications with the Ariadne UI.
"""

from typing import Any
from .message import BotResponse


class LangGraphAdapter:
    """Adapter to stream LangGraph events to Ariadne responses.

    Usage:
        adapter = LangGraphAdapter(response)
        async for event in graph.astream_events(state, version="v2"):
            if adapter.handle_event(event):
                continue  # Event was handled
            # Handle custom events here

        adapter.finish()
    """

    def __init__(self, response: BotResponse):
        self.response = response
        self.current_agent: str | None = None
        self.streaming_content: str = ""
        self._finished = False

    def handle_event(self, event: dict[str, Any]) -> bool:
        """Handle a LangGraph event.

        Returns True if the event was handled, False otherwise.
        """
        if self.response.is_cancelled:
            return True

        kind = event.get("event", "")

        if kind == "on_chain_start":
            return self._handle_chain_start(event)
        elif kind == "on_chain_end":
            return self._handle_chain_end(event)
        elif kind == "on_chat_model_start":
            return self._handle_model_start(event)
        elif kind == "on_chat_model_stream":
            return self._handle_model_stream(event)
        elif kind == "on_chat_model_end":
            return self._handle_model_end(event)
        elif kind == "on_tool_start":
            return self._handle_tool_start(event)
        elif kind == "on_tool_end":
            return self._handle_tool_end(event)
        elif kind == "on_tool_error":
            return self._handle_tool_error(event)

        return False

    def _handle_chain_start(self, event: dict) -> bool:
        """Handle chain/agent start."""
        name = event.get("name", "")
        # Skip internal chains
        if name in ("RunnableSequence", "LangGraph", "ChannelWrite"):
            return True

        self.current_agent = name
        self.response.set_status(f"Agent: {name}", "Starting...")
        return True

    def _handle_chain_end(self, event: dict) -> bool:
        """Handle chain/agent end."""
        name = event.get("name", "")
        if name == "LangGraph":
            self._extract_final_response(event)
        return True

    def _handle_model_start(self, event: dict) -> bool:
        """Handle LLM start."""
        if self.current_agent:
            self.response.set_status(f"Agent: {self.current_agent}", "Thinking...")
        else:
            self.response.thinking("Processing...")
        self.streaming_content = ""
        return True

    def _handle_model_stream(self, event: dict) -> bool:
        """Handle streaming LLM output."""
        chunk = event.get("data", {}).get("chunk")
        if chunk and hasattr(chunk, "content"):
            content = chunk.content
            if isinstance(content, str):
                self.streaming_content += content
                # Show preview in status
                preview = self.streaming_content[-100:].replace("\n", " ")
                if self.current_agent:
                    self.response.set_status(
                        f"Agent: {self.current_agent}",
                        preview
                    )
                else:
                    self.response.thinking(preview)
        return True

    def _handle_model_end(self, event: dict) -> bool:
        """Handle LLM end."""
        return True

    def _handle_tool_start(self, event: dict) -> bool:
        """Handle tool start."""
        tool_name = event.get("name", "unknown")
        tool_input = event.get("data", {}).get("input", {})

        # Format input for display
        if isinstance(tool_input, dict):
            input_str = ", ".join(f"{k}={v!r}" for k, v in tool_input.items())
        else:
            input_str = str(tool_input)

        # Truncate if too long
        if len(input_str) > 100:
            input_str = input_str[:100] + "..."

        self.response.tool(tool_name, input_str)
        return True

    def _handle_tool_end(self, event: dict) -> bool:
        """Handle tool end."""
        # Tool completed successfully, status will be updated by next action
        return True

    def _handle_tool_error(self, event: dict) -> bool:
        """Handle tool error."""
        tool_name = event.get("name", "unknown")
        error = event.get("data", {}).get("error")
        error_str = str(error) if error else "Unknown error"

        # Truncate if too long
        if len(error_str) > 200:
            error_str = error_str[:200] + "..."

        self.response.tool_error(tool_name, error_str)
        return True

    def _extract_final_response(self, event: dict) -> None:
        """Extract and set the final response from graph output."""
        output = event.get("data", {}).get("output", {})
        messages = output.get("messages", [])

        # Find the last AI message with content
        final_content = None
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content:
                # Skip tool calls
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    continue
                final_content = msg.content
                break

        if final_content:
            self.response.complete(final_content)
            self._finished = True

    def finish(self, default_message: str = "Task completed.") -> None:
        """Finish the response if not already finished."""
        if not self._finished and not self.response.is_cancelled:
            if self.streaming_content:
                self.response.complete(self.streaming_content)
            else:
                self.response.complete(default_message)
            self._finished = True


async def run_langgraph(
    graph,
    state: dict,
    response: BotResponse,
    *,
    version: str = "v2",
) -> dict:
    """Run a LangGraph and stream events to an Ariadne response.

    Args:
        graph: Compiled LangGraph
        state: Initial state dict
        response: Ariadne BotResponse to update
        version: Event stream version (default "v2")

    Returns:
        Final state from the graph

    Example:
        @ui.on_message
        async def handle(message: str, response: BotResponse):
            state = {"messages": [HumanMessage(content=message)]}
            await run_langgraph(my_graph, state, response)
    """
    adapter = LangGraphAdapter(response)
    final_state = None

    async for event in graph.astream_events(state, version=version):
        if response.is_cancelled:
            break
        adapter.handle_event(event)

        # Capture final state
        if event.get("event") == "on_chain_end":
            if event.get("name") == "LangGraph":
                final_state = event.get("data", {}).get("output")

    adapter.finish()
    return final_state or state
