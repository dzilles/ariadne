import os
import logging
from typing import List, Any
from langchain_core.messages import messages_to_dict, messages_from_dict, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from src.configuration.llm_factory import get_llm
from src.tools.plane_client import PlaneInteraction
from src.tools.pm_tools import ProjectManagementAgentTools
from src.tools.file_tools import FileAgentTools
from src.tools.git_tools import GitAgentTools
from src.tools.tool_wrapper import wrap_tools_with_error_handling
from src.configuration.vault import Vault

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
            self.client = PlaneInteraction(api_key=api_key)
            self.pm_tools = ProjectManagementAgentTools(self.client)
            self.file_tools = FileAgentTools()
            self.git_tools = GitAgentTools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # Register Tools (wrapped for error handling)
        self.tools = wrap_tools_with_error_handling([
            # Reading Inputs
            self.pm_tools.get_ticket_details,
            self.file_tools.read_file,
            self.file_tools.list_files,

            # Writing Outputs
            self.file_tools.write_file,

            # Linking/Updating
            self.pm_tools.add_comment,
            self.pm_tools.add_link,
            self.pm_tools.update_ticket,
            self.pm_tools.attach_file,

            # Analysis/Search
            self.pm_tools.search_tickets,
            self.file_tools.search_files,

            # Git Operations
            self.git_tools.get_status,
            self.git_tools.get_current_branch,
            self.git_tools.create_branch,
            self.git_tools.add_files,
            self.git_tools.commit_changes
        ])

        # Collect Tool Documentation
        self.tool_docs = "\n".join([
            self.pm_tools.get_tool_descriptions(),
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
        return f"""You are a Senior Requirements Engineer in the Ariadne V-Model lifecycle.
Your goal is to analyze User Stories from Plane tickets and expand them into detailed Requirement Documents.

### Workflow:
1.  **Analyze Ticket:** 
    *   When asked to process a ticket (e.g., #25), use `get_ticket_details` to read the User Story and Acceptance Criteria.
    *   **Status Update:** Immediately update the ticket status to 'In Progress' to indicate work has started.
2.  **Check Comments:** **CRITICAL:** Review the ticket comments. If there are any open questions, unresolved feedback, or "todo" items, you MUST address them before proceeding.
3.  **Git Branching:** Before creating any files, check your current branch. If you are on 'main', create a new feature branch named `req/ticket-{{id}}`.
4.  **Gap Analysis:** Critically evaluate the information. Is it detailed enough to write a strict specification?
    *   *If vague:* Do NOT draft the document yet. Identify specific questions (e.g., "What specific tools should the agent use?", "What is the expected output format?").
    *   *Action:* Use `add_comment` to post these questions on the ticket to the Product Owner/User. Inform the user you are waiting for clarification.
4.  **Draft Requirements (Only if detailed):**
    *   If the ticket has sufficient detail OR if the user explicitly instructs you to "proceed with assumptions", create the document.
    *   Filename: `docs/requirements/REQ-{{ticket_id}}.md`
    *   Content must include: Introduction, User Requirements (UR), Functional Requirements (FR), Non-Functional Requirements (NFR), Assumptions.
5.  **Save & Version:** 
    *   Use `write_file` to save the content.
    *   Use `add_files` and `commit_changes` to stage and commit the new requirement document to your feature branch.
6.  **Finalize Ticket:** 
    *   Update the **Ticket Description** using `update_ticket`. The new description must include the original User Story PLUS a "Traceability" section containing:
        *   **Git Branch:** <branch_name>
        *   **Latest Commit:** <commit_hash>
        *   **Files Changed:** A list of files created/modified.
        *   **Summary:** A short description of the changes made.
    *   Use `update_ticket` to set the status to "Ready for Review".
    *   Use `add_comment` to notify the user that the requirement gathering is complete.

### Guiding Principles:
*   **Ask, don't guess:** Prefer asking for clarification over making broad assumptions.
*   **Quality Criteria (The Good Requirement):**
    *   **Atomic:** Each requirement should describe a single concept or feature.
    *   **Unambiguous:** Avoid vague words like "fast", "user-friendly", or "roughly". Use precise metrics.
    *   **Verifiable:** It must be possible to write a definitive test case (Pass/Fail) for the requirement.
    *   **Necessary:** Every requirement must trace back to a business need or user value.
*   Do NOT write code implementation details. Focus on WHAT, not HOW.

### Available Tools:
{self.tool_docs}
"""

if __name__ == "__main__":
    agent = RequirementsAgent()
    print("Requirements Agent initialized.")