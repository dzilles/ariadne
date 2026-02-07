import logging
from typing import List

from langchain_core.messages import messages_to_dict, messages_from_dict, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from src.configuration.llm_factory import get_llm
from src.tools.plane_client import PlaneInteraction
from src.tools.pm_tools import ProjectManagementAgentTools
from src.tools.file_tools import FileAgentTools
from src.tools.tool_wrapper import wrap_tools_with_error_handling
from src.configuration.vault import Vault

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class QualityAssuranceAgent:
    """
    QA Agent responsible for Testing and Validation.
    """

    def __init__(self):
        self.llm = get_llm()

        # Load Agent-Specific Plane Key from Vault
        api_key = Vault.get_secret("QA_AGENT_API_KEY")
        if not api_key:
            api_key = Vault.get_secret("PLANE_API_TOKEN")
        if not api_key:
            raise ValueError("PLANE_API_TOKEN required. Use '/secret PLANE_API_TOKEN <key>'")

        try:
            self.client = PlaneInteraction(api_key=api_key)
            self.pm_tools = ProjectManagementAgentTools(self.client)
            self.file_tools = FileAgentTools()
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

            # Writing - QA might need to write test plans or bug reports
            self.file_tools.write_file,

            # Plane Updates
            self.pm_tools.add_comment,
            self.pm_tools.update_ticket,
            self.pm_tools.search_tickets,
            self.pm_tools.create_ticket # For creating bugs
        ])

        # Auto-document tools
        self.tool_docs = "\n".join([
            self.pm_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions()
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
             final_str = "".join(text_parts).strip()
             return final_str if final_str else "[Action Performed]"
             
        return str(content)

    def _get_system_message(self) -> str:
        return f"""You are a Quality Assurance Engineer specializing in Code Review and Standards.
Your goal is to ensure the software meets architectural guidelines and coding standards.

### Responsibilities:
1.  **Code Review:** Review code changes for quality, readability, and adherence to patterns.
2.  **Verify Standards:** Ensure coding conventions (PEP 8, typing) are followed.
3.  **Approve/Reject:** Provide feedback on pull requests or code submissions.
4.  **Process Check:** specific that the development process (V-Model) steps have been followed.

### Available Tools:
{self.tool_docs}
"""
