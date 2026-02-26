import logging
from src.agents.base_agent import BaseAgent
from src.tools.plane_client import PlaneInteraction
from src.tools.pm_tools import ProjectManagementAgentTools
from src.tools.file_tools import FileAgentTools
from src.tools.tool_wrapper import wrap_tools_with_error_handling

logger = logging.getLogger(__name__)

class QualityAssuranceAgent(BaseAgent):
    """
    QA Agent responsible for Testing and Validation.
    """

    def __init__(self):
        super().__init__("QA_AGENT_API_KEY")

        try:
            self.client = PlaneInteraction(api_key=self.api_key)
            self.pm_tools = ProjectManagementAgentTools(self.client)
            self.file_tools = FileAgentTools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        self.tools = wrap_tools_with_error_handling([
            self.pm_tools.get_ticket_details,
            self.file_tools.read_file,
            self.file_tools.list_files,
            self.file_tools.search_files,
            self.file_tools.write_file,
            self.pm_tools.add_comment,
            self.pm_tools.update_ticket,
            self.pm_tools.search_tickets,
            self.pm_tools.create_ticket
        ])

        self.tool_docs = "\n".join([
            self.pm_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions()
        ])

        self._init_executor(self.tools, self._get_system_message())

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