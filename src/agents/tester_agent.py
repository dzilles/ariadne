import logging
from src.agents.base_agent import BaseAgent
from src.tools.plane_client import PlaneInteraction
from src.tools.pm_tools import ProjectManagementAgentTools
from src.tools.file_tools import FileAgentTools
from src.tools.git_tools import GitAgentTools
from src.tools.tool_wrapper import wrap_tools_with_error_handling

logger = logging.getLogger(__name__)

class TesterAgent(BaseAgent):
    """
    Tester Agent responsible for writing and executing tests.
    """

    def __init__(self):
        super().__init__("TESTER_AGENT_API_KEY")

        try:
            self.client = PlaneInteraction(api_key=self.api_key)
            self.pm_tools = ProjectManagementAgentTools(self.client)
            self.file_tools = FileAgentTools()
            self.git_tools = GitAgentTools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        self.tools = wrap_tools_with_error_handling([
            self.pm_tools.get_ticket_details,
            self.file_tools.read_file,
            self.file_tools.list_files,
            self.file_tools.search_files,
            self.file_tools.write_file,
            self.git_tools.get_status,
            self.git_tools.get_current_branch,
            self.git_tools.create_branch,
            self.git_tools.checkout_branch,
            self.git_tools.add_files,
            self.git_tools.commit_changes,
            self.pm_tools.add_comment,
            self.pm_tools.update_ticket,
            self.pm_tools.search_tickets
        ])

        self.tool_docs = "\n".join([
            self.pm_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions(),
            self.git_tools.get_tool_descriptions()
        ])

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are a Software Tester.
Your goal is to write comprehensive tests for the software.

### Responsibilities:
1.  **Write Tests:** Create unit, integration, and system tests based on requirements and code.
2.  **Ensure Coverage:** Aim for high code coverage and test edge cases.
3.  **Validate:** Ensure tests pass locally before committing.
4.  **Document:** Document test cases and instructions.

### Available Tools:
{self.tool_docs}
"""