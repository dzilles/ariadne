import logging
from typing import Any, List

from langchain_core.messages import (
    messages_to_dict,
    messages_from_dict,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langgraph.prebuilt import create_react_agent

from src.ariadne.llm.factory import get_llm
from src.ariadne.runtime.token_usage import (
    extract_token_usage,
    notify_active_work_item_token_usage,
)

# Setup logging
logger = logging.getLogger(__name__)


class BaseAgent:
    """
    Base Agent class that handles common boilerplate for all Ariadne agents.
    Provides standard LLM initialization, history management, and chat loop execution.
    """

    def __init__(self):
        self.llm = get_llm()

        self.chat_history = []
        self.agent_executor = None  # To be initialized by subclasses

    def _get_current_prompt(self, state: dict):
        """Dynamic prompt callback for the LangGraph agent."""
        return [SystemMessage(content=self.current_prompt)] + state.get("messages", [])

    def _init_executor(self, tools: list, system_message: str):
        """Initializes the underlying LangGraph React agent."""
        self.system_message = system_message
        self.current_prompt = system_message
        self.tools = tools
        self.agent_executor = create_react_agent(
            self.llm, tools, prompt=self._get_current_prompt
        )
        # Increase recursion limit to avoid early termination on complex tasks
        self.agent_executor.config = {"recursion_limit": 50}

    def set_mission_instructions(self, instructions: str):
        """Updates the agent's system prompt with dynamic mission-specific instructions."""
        self.current_prompt = f"{self.system_message}\n\n{instructions}"
        logger.info("Agent mission instructions updated.")

    def _completion_protocol(self) -> str:
        """Instructions for agents that return control to the Orchestrator."""
        return """### Completion Protocol
When your delegated task is complete or blocked, call `return_to_orchestrator(...)` exactly once as your final tool call.
Use `SUCCESS` when your delegated task is complete.
Use `FAILED` when you cannot complete it, are blocked, or need Orchestrator/user intervention.
You provide only semantic handoff information: `status`, `summary`, optional `details`, `decisions`, `blockers`, intentional `artifacts`, `verification`, and `gate_decision`.
Report artifact paths and gate decisions in this completion. The coordinator persists links, gates, commits, status changes, and shared context after validating the result.
Do not choose the next agent or next workflow action. The Orchestrator decides that.
Do not manually report git status, changed files, commits, or diff stats. Those are collected automatically.
Do not call `finish_agent_run`; it exists only as a temporary compatibility alias.
After `return_to_orchestrator` returns, do not call another tool."""

    def get_history(self) -> List[dict]:
        """Returns the current chat history as a serializable list of dicts."""
        return messages_to_dict(self.chat_history)

    def get_context(self) -> dict[str, Any]:
        """Return the full prompt and chat context for persistence."""
        return {
            "schema_version": 2,
            "system_message": self.system_message,
            "current_prompt": self.current_prompt,
            "chat_history": self.get_history(),
        }

    def load_context(self, context_data: dict[str, Any] | list[dict]) -> None:
        """Load a full prompt/chat context, accepting legacy history lists."""
        if isinstance(context_data, list):
            self.load_history(context_data)
            return

        self.system_message = str(
            context_data.get("system_message") or self.system_message
        )
        self.current_prompt = str(
            context_data.get("current_prompt") or self.system_message
        )
        self.load_history(context_data.get("chat_history", []))

    def load_history(self, history_data: List[dict]):
        """Loads chat history from a list of dicts."""
        try:
            self.chat_history = messages_from_dict(history_data)
            logger.info(f"Loaded {len(self.chat_history)} messages into history.")
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
            raise

    def clear_history(self):
        """Clears the chat history."""
        self.chat_history = []
        logger.info("Chat history cleared.")

    def chat(self, user_input: str) -> str:
        """
        Interacts with the agent while maintaining chat history and handling tool responses.
        """
        logger.info(f"User Input: {user_input}")

        # Add user message to history
        start_index = len(self.chat_history)
        self.chat_history.append(HumanMessage(content=user_input))

        if not self.agent_executor:
            raise RuntimeError(
                "Agent executor not initialized. Subclasses must call _init_executor()."
            )

        # Invoke agent
        inputs = {"messages": self.chat_history}
        try:
            result = self.agent_executor.invoke(inputs)
        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            if getattr(self, "_propagate_delegation_errors", False):
                raise
            error_msg = f"[System Error: {str(e)}]"
            # Add error to history so LLM has context on next turn
            self.chat_history.append(AIMessage(content=error_msg))
            return error_msg

        # Update history
        self.chat_history = result["messages"]
        usage = extract_token_usage(self.chat_history[start_index:])
        notify_active_work_item_token_usage(usage)

        # Get last message
        last_msg = self.chat_history[-1]
        content = last_msg.content

        # Handle list content (common with some LLM providers like Anthropic/Gemini returning rich text)
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])

            final_content = "".join(text_parts).strip()

            # Sometimes models return empty content but make a tool call
            if (
                not final_content
                and hasattr(last_msg, "tool_calls")
                and last_msg.tool_calls
            ):
                action_msg = f"[Action Taken: {last_msg.tool_calls[0].get('name')}]"
                logger.info(f"Agent Response: {action_msg}")
                return action_msg

            logger.info(f"Agent Response: {final_content}")
            return final_content

        final_str = str(content)
        if not final_str.strip():
            return "[System Warning: The AI returned an empty response. This might be due to server overload or safety filters.]"

        logger.info(f"Agent Response: {final_str}")
        return final_str
