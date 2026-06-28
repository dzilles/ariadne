import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.work_items.tools import StandardTicketTools
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class QualityAssuranceAgent(BaseAgent):
    """
    QA Agent responsible for Testing and Validation.
    """

    def __init__(self, ticket_tools=None, file_tools=None):
        super().__init__("QA_AGENT_API_KEY")

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_ticket_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # Map to expected tool names
        self.get_ticket_details = self.ticket_tools.get_ticket
        self.update_ticket = self.ticket_tools.update_status
        self.add_comment = self.ticket_tools.post_comment

        self.tools = wrap_tools_with_error_handling([
            self.get_ticket_details,
            self.file_tools.read_file,
            self.file_tools.list_files,
            self.file_tools.search_files,
            self.file_tools.write_file,
            self.add_comment,
            self.update_ticket
        ])

        self.tool_docs = "\n".join([
            self.ticket_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions()
        ])

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are a Quality Assurance Engineer specializing in Code Review and Standards.
Your goal is to ensure the software meets architectural guidelines and coding standards.

### Responsibilities:
1.  **Code Review:** Review code changes for quality, readability, and adherence to patterns.
2.  **Verify Standards:** Ensure coding conventions (PEP 8, typing) are followed.
3.  **Approve/Reject:** Provide feedback on code submissions.
4.  **Process Check:** ensure that the development process (V-Model) steps have been followed in the project management system.

### Available Tools:
{self.tool_docs}
"""
