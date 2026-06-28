import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.tools.git_tools import GitAgentTools
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class TesterAgent(BaseAgent):
    """
    Tester Agent responsible for writing and executing tests.
    """

    def __init__(self, ticket_tools=None, file_tools=None, git_tools=None):
        super().__init__("TESTER_AGENT_API_KEY")

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_work_item_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
            self.git_tools = git_tools or DependencyRegistry.get_git_tools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # Map to expected tool names
        self.get_ticket_details = self.ticket_tools.get_work_item
        self.update_ticket = self.ticket_tools.update_status
        self.add_comment = self.ticket_tools.post_comment

        self.tools = wrap_tools_with_error_handling([
            self.get_ticket_details,
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
            self.add_comment,
            self.update_ticket
        ])

        self.tool_docs = "\n".join([
            self.ticket_tools.get_tool_descriptions(),
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
