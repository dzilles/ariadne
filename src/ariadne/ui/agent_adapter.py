"""Agent adapter for bridging sync agents with async TUI.

This module provides utilities to run the project's synchronous agent.chat()
methods within the async TUI context.
"""

import asyncio
from typing import Any

from langchain_core.messages import HumanMessage, AIMessage

from .message import BotResponse
import src.ariadne.tools.tool_wrapper as tool_wrapper
from src.ariadne.runtime import run_manager
from src.ariadne.runtime.token_usage import (
    extract_token_usage,
    notify_active_work_item_token_usage,
)

from src.ariadne.agents.requirements_agent import RequirementsAgent
from src.ariadne.agents.architect_agent import ArchitectAgent
from src.ariadne.agents.developer_agent import DeveloperAgent
from src.ariadne.agents.tester_agent import TesterAgent
from src.ariadne.agents.qa_agent import QualityAssuranceAgent
from src.ariadne.agents.qm_agent import QMAgent
from src.ariadne.agents.orchestrator_agent import OrchestratorAgent

# Agent registry mapping names to classes
AGENT_CLASSES = {
    "Orchestrator": OrchestratorAgent,
    "Requirements": RequirementsAgent,
    "QM": QMAgent,
    "Architect": ArchitectAgent,
    "Developer": DeveloperAgent,
    "Tester": TesterAgent,
    "QA": QualityAssuranceAgent,
}

# Agent descriptions for UI display
AGENT_DESCRIPTIONS = {
    "Orchestrator": "Manages backlog and coordinates the overall workflow",
    "Requirements": "Refines tickets into detailed requirement documents",
    "QM": "Reviews requirement documents for completeness and clarity",
    "Architect": "Designs system architecture and technical specifications",
    "Developer": "Implements features and fixes bugs based on designs",
    "Tester": "Writes and executes automated tests",
    "QA": "Reviews code and validates adherence to quality standards",
}

# Patterns that indicate an error response from agents
ERROR_PATTERNS = [
    "[System Error:",
    "[System Warning:",
    "[Error:",
    "[Action Taken:",  # Often indicates tool ran but no real response
]


def _is_error_response(result: str) -> bool:
    """Check if the agent's response indicates an error."""
    if not result:
        return True
    for pattern in ERROR_PATTERNS:
        if result.strip().startswith(pattern):
            return True
    return False


async def handle_message(
    message: str,
    response: BotResponse,
    agent: Any,
) -> None:
    """Adapter to run agent in async context with status updates.

    If the agent has an agent_executor (LangGraph), uses streaming events
    to show tool calls. Otherwise falls back to running chat() in a thread pool.

    Args:
        message: The user's message to send to the agent
        response: The BotResponse object to update with status and results
        agent: The agent instance with a chat() method
    """
    agent_name = agent.__class__.__name__
    run_state = run_manager.start_run(agent_name, message)
    # Check if agent has a LangGraph executor we can stream from
    try:
        if hasattr(agent, "agent_executor") and hasattr(agent, "chat_history"):
            await _handle_message_streaming(message, response, agent)
        else:
            await _handle_message_sync(message, response, agent)
        run_manager.finish_run(run_state.id)
    except Exception:
        run_manager.fail_run(run_state.id)
        raise


async def _handle_message_streaming(
    message: str,
    response: BotResponse,
    agent: Any,
) -> None:
    """Handle message using LangGraph with tool approval support.

    Runs agent execution in a thread pool to allow blocking tool approval
    while keeping the UI responsive.
    """
    response.thinking("Processing your request...")

    # Store the main event loop for the approval callback
    main_loop = asyncio.get_running_loop()
    tool_wrapper._event_loop = main_loop

    def run_agent_sync():
        """Run the agent synchronously in a thread."""
        start_index = len(agent.chat_history)
        agent.chat_history.append(HumanMessage(content=message))
        inputs = {"messages": agent.chat_history}
        result = agent.agent_executor.invoke(inputs)
        return result, start_index

    try:
        # Run the agent in a thread pool executor
        task = main_loop.run_in_executor(None, run_agent_sync)

        # Poll for completion or cancellation
        while not task.done():
            if response.is_cancelled:
                run_manager.request_cancel()
            await asyncio.sleep(0.1)

        # Check if cancelled while getting result
        if response.is_cancelled:
            run_manager.request_cancel()
            return

        result, start_index = task.result()

        # Update history from result
        if "messages" in result:
            agent.chat_history = result["messages"]
            usage = extract_token_usage(agent.chat_history[start_index:])
            response.set_token_usage(usage)
            notify_active_work_item_token_usage(usage)

        # Extract final response
        if agent.chat_history:
            last_msg = agent.chat_history[-1]
            content = last_msg.content

            # Handle list content (like from Anthropic)
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict) and "text" in part:
                        text_parts.append(part["text"])
                final_str = "".join(text_parts).strip()
                content = final_str if final_str else "[Action Performed]"

            if _is_error_response(str(content)):
                response.error(str(content))
            else:
                response.complete(str(content))

    except asyncio.CancelledError:
        # Response already marked as cancelled
        pass
    except Exception as e:
        error_msg = f"[System Error: {str(e)}]"
        agent.chat_history.append(AIMessage(content=error_msg))
        response.error(f"Agent error: {str(e)}")


async def _handle_message_sync(
    message: str,
    response: BotResponse,
    agent: Any,
) -> None:
    """Handle message using synchronous chat() in thread pool (fallback)."""
    response.thinking("Processing your request...")

    # Store the main event loop for callbacks
    main_loop = asyncio.get_running_loop()
    tool_wrapper._event_loop = main_loop

    try:
        # Run the synchronous chat() method in a thread pool executor
        start_index = len(getattr(agent, "chat_history", []))
        task = main_loop.run_in_executor(None, agent.chat, message)

        # Poll for completion or cancellation
        while not task.done():
            if response.is_cancelled:
                run_manager.request_cancel()
            await asyncio.sleep(0.1)

        # Check if cancelled while getting result
        if response.is_cancelled:
            run_manager.request_cancel()
            return

        result = task.result()
        usage = extract_token_usage(getattr(agent, "chat_history", [])[start_index:])
        response.set_token_usage(
            usage
        )

        # Check if the result is an error message from the agent
        if result:
            if _is_error_response(result):
                response.error(result)
            else:
                response.complete(result)
        else:
            response.error("Agent returned empty response")

    except asyncio.CancelledError:
        # Response already marked as cancelled
        pass
    except Exception as e:
        response.error(f"Agent error: {str(e)}")


def get_agent_names() -> list[str]:
    """Get list of available agent names."""
    return list(AGENT_CLASSES.keys())
