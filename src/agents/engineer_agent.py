import os
import logging
from typing import List

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

class EngineerAgent:
    """
    Engineer Agent responsible for Software Design and Implementation.
    Phase 3: Design (DESIGN-*.md)
    Phase 4: Implementation (Source Code)
    """

    def __init__(self):
        self.llm = get_llm()

        # Load Agent-Specific Plane Key from Vault
        api_key = Vault.get_secret("ENGINEER_AGENT_API_KEY")
        if not api_key:
            api_key = Vault.get_secret("PLANE_API_TOKEN")
        if not api_key:
            raise ValueError("PLANE_API_TOKEN required. Use '/secret PLANE_API_TOKEN <key>'")

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
            # Reading
            self.pm_tools.get_ticket_details,
            self.file_tools.read_file,
            self.file_tools.list_files,
            self.file_tools.search_files,

            # Writing
            self.file_tools.write_file,

            # Git
            self.git_tools.get_status,
            self.git_tools.get_current_branch,
            self.git_tools.create_branch,
            self.git_tools.checkout_branch,
            self.git_tools.add_files,
            self.git_tools.commit_changes,

            # Plane Updates
            self.pm_tools.add_comment,
            self.pm_tools.update_ticket,
            self.pm_tools.search_tickets
        ])

        # Auto-document tools
        self.tool_docs = "\n".join([
            self.pm_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions(),
            self.git_tools.get_tool_descriptions()
        ])

        self.agent_executor = create_react_agent(self.llm, self.tools, prompt=self._get_system_message())
        self.chat_history = []

    def get_history(self) -> List[dict]:
        return messages_to_dict(self.chat_history)

    def load_history(self, history_data: List[dict]):
        self.chat_history = messages_from_dict(history_data)

    def clear_history(self):
        self.chat_history = []

    def chat(self, user_input: str) -> str:
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
        
        # Handle response content extraction similar to other agents
        content = last_msg.content
        if isinstance(content, list):
             # Extract text from list of dicts/strings
             text_parts = []
             for part in content:
                 if isinstance(part, str): text_parts.append(part)
                 elif isinstance(part, dict) and "text" in part: text_parts.append(part["text"])
             final_str = "".join(text_parts).strip()
             return final_str if final_str else "[Action Performed]"
             
        return str(content)

    def _get_system_message(self) -> str:
        return f"""You are a Senior Systems Engineer in the Ariadne V-Model lifecycle.
Your goal is to transform Functional Specifications (SPEC) into Technical Designs and working Code.

### Workflow:

1.  **Analyze Request:**
    *   **Status Update:** Immediately update the ticket status to 'In Progress'.
    *   Read the Ticket using `get_ticket_details`.
    *   **CRITICAL:** Check the ticket comments. If there are unresolved questions or feedback, you MUST address them before starting design or code.
    *   Locate and read the corresponding Specification file (`docs/specs/SPEC-{{id}}.md`) using `read_file`.

2.  **Git Setup:**
    *   Check `get_current_branch`.
    *   Create a feature branch: `dev/ticket-{{id}}` using `create_branch`.

3.  **Phase A: Technical Design (If requested or missing):**
    *   Create a Design Document: `docs/design/DESIGN-{{id}}.md`.
    *   Content: Modules, Class Diagrams (Mermaid), Function Signatures, Algorithms.
    *   **Commit:** Stage and commit this file (`Feat: Added Design for #{{id}}`).

4.  **Phase B: Implementation (Coding):**
    *   Write the actual Python code in `src/` based on the Design.
    *   Ensure code is strictly typed and documented.
    *   **Commit:** Stage and commit code files (`Feat: Implemented logic for #{{id}}`).

5.  **Finalize Ticket:**
    *   Update the **Ticket Description** using `update_ticket`. Append a "Traceability" section:
        *   **Git Branch:** <branch>
        *   **Commit:** <hash>
        *   **Artifacts:** List of files (Design + Code).
    *   Set status to "Ready for Review".
    *   Post a comment confirming completion.

### Guiding Principles:
*   **Code Quality:** PEP 8 standards, Type Hints, Docstrings.
*   **Traceability:** Every piece of code must link back to a requirement in the DESIGN or SPEC doc.
*   **Safety:** Do not overwrite existing files without reading them first.

### Available Tools:
{self.tool_docs}
"""