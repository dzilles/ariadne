import os
import logging
from typing import List, Any
from langchain_core.messages import messages_to_dict, messages_from_dict, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from src.configuration.llm_factory import get_llm
from src.interfaces.plane_adapter import PlaneTicketSystem
from src.tools.ticket_tools import StandardTicketTools
from src.tools.file_tools import FileAgentTools
from src.tools.git_tools import GitAgentTools
from src.tools.tool_wrapper import wrap_tools_with_error_handling
from src.configuration.vault import Vault
from src.workflows.enforcement import ToolGuard

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RequirementsAgent:
    """
    Requirements Agent responsible for refining Plane tickets into detailed Requirement Documents.
    This corresponds to the 'Requirement Gathering' phase of the V-Model.
    """

    def __init__(self):
        """
        Initialize the Requirements Agent.
        """
        self.llm = get_llm()

        # Load Agent-Specific Plane Key from Vault
        api_key = Vault.get_secret("REQUIREMENTS_AGENT_API_KEY")
        if not api_key:
            api_key = Vault.get_secret("PLANE_API_TOKEN")
        if not api_key:
            raise ValueError("PLANE_API_TOKEN required. Use '/secret PLANE_API_TOKEN <key>'")

        # Initialize Tools
        try:
            self.ticket_system = PlaneTicketSystem(api_key=api_key)
            self.ticket_tools = StandardTicketTools(self.ticket_system)
            self.file_tools = FileAgentTools()
            self.git_tools = GitAgentTools()
            
            # Initialize Guard
            self.guard = ToolGuard(self.ticket_system, agent_name="Requirements")
            
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # Raw Tools List
        raw_tools = [
            # The Activation Tool (Crucial)
            self.guard.activate_ticket,
            
            # Ticket System Tools
            self.ticket_tools.get_ticket, # Used for discovery before activation
            self.ticket_tools.update_status,
            self.ticket_tools.post_comment,
            self.ticket_tools.approve_gate,
            self.ticket_tools.reject_gate,
            self.ticket_tools.add_link,

            # Reading Inputs
            self.file_tools.read_file,
            self.file_tools.list_files,

            # Writing Outputs
            self.file_tools.write_file,

            # Analysis/Search
            self.file_tools.search_files,

            # Git Operations
            self.git_tools.get_status,
            self.git_tools.get_current_branch,
            self.git_tools.create_branch,
            self.git_tools.add_files,
            self.git_tools.commit_changes
        ]

        # Wrap tools with Guard middleware
        self.tools = wrap_tools_with_error_handling(self.guard.wrap_tools(raw_tools))

        # Collect Tool Documentation
        self.tool_docs = "\n".join([
            "### Core Workflow Tool",
            "* `activate_ticket(ticket_id)`: **MUST CALL FIRST**. Locks context to a ticket and validates rules.",
            self.ticket_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions(),
            self.git_tools.get_tool_descriptions()
        ])

        # Define the Agent
        self.agent_executor = create_react_agent(self.llm, self.tools, prompt=self._get_system_message())

        # Initialize chat history
        self.chat_history = []

    def get_history(self) -> List[dict]:
        """Returns the current chat history as a serializable list of dicts."""
        return messages_to_dict(self.chat_history)

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
        Interacts with the agent while maintaining chat history.
        """
        logger.info(f"User Input: {user_input}")
        self.chat_history.append(HumanMessage(content=user_input))
        
        inputs = {"messages": self.chat_history}
        try:
            result = self.agent_executor.invoke(inputs)
        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            error_msg = f"[System Error: {str(e)}]"
            # Add error to history so LLM has context on next turn
            self.chat_history.append(AIMessage(content=error_msg))
            return error_msg
        
        self.chat_history = result["messages"]
        last_msg = self.chat_history[-1]
        content = last_msg.content
        
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, str): text_parts.append(part)
                elif isinstance(part, dict) and "text" in part: text_parts.append(part["text"])
            final_content = "".join(text_parts).strip()
            
            if not final_content and hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                 action_msg = f"[Action Taken: {last_msg.tool_calls[0].get('name')}]"
                 logger.info(f"Agent Response: {action_msg}")
                 return action_msg
            
            logger.info(f"Agent Response: {final_content}")
            return final_content
            
        final_str = str(content)
        if not final_str.strip():
             return "[System Warning: The AI returned an empty response.]"
             
        logger.info(f"Agent Response: {final_str}")
        return final_str

    def _get_system_message(self) -> str:
        return f"""You are the Requirements Agent in the Ariadne V-Model lifecycle.

### CRITICAL PROTOCOL:
1.  **Activate First:** You cannot perform ANY action (writing files, committing code) until you successfully call `activate_ticket(ticket_id)`.
2.  **Verify Rules:** The `activate_ticket` tool will tell you if you are allowed to work. If it fails (e.g. "Access Denied"), you must stop and inform the user.
3.  **Follow Instructions:** Once activated, the system will provide you with specific instructions (Mission, Allowed Actions, Required Outputs) for that ticket. Follow them precisely.

### Workflow:
1.  User says "Work on #25".
2.  You call `activate_ticket("25")`.
3.  If successful, proceed with the instructions provided in the tool output.
    *   Typically: Read User Story -> Draft REQ-*.md -> Link Artifact -> Approve Gate.

### Available Tools:
{self.tool_docs}
"""

if __name__ == "__main__":
    agent = RequirementsAgent()
    print("Requirements Agent initialized.")