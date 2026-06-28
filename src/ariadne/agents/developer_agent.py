import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.tools.git_tools import GitAgentTools
from src.ariadne.tools.shell_tools import ShellAgentTools
from src.ariadne.work_items.tools import StandardTicketTools
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class DeveloperAgent(BaseAgent):
    """
    Developer Agent responsible for Implementation and Coding.
    """

    def __init__(self, ticket_tools=None, file_tools=None, git_tools=None, shell_tools=None):
        super().__init__("DEVELOPER_AGENT_API_KEY")

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_ticket_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
            self.git_tools = git_tools or DependencyRegistry.get_git_tools()
            self.shell_tools = shell_tools or DependencyRegistry.get_shell_tools()
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
            self.shell_tools.run_shell_command,
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
            self.git_tools.get_tool_descriptions(),
            self.shell_tools.get_tool_descriptions()
        ])

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are a Software Developer.
Your goal is to implement features and fix bugs based on technical designs and requirements.

### Responsibilities:
1.  **Implement:** Write clean, efficient, and well-documented code.
2.  **Follow Design:** Adhere to the provided architectural designs (DESIGN-*.md).
3.  **Git Workflow:** Create branches, commit often, and push changes.
4.  **Update Tickets:** Keep the ticket status updated as you work in the project management system.
5.  **Code-Level Traceability:** When modifying functions/classes, you MUST include a traceability tag in the docstring or comment: `Implementation of ARCH-XXX. Fulfills REQ-XXX.`
6.  **Verify:** After making code changes, ALWAYS run simple developer tests (e.g., `python -m py_compile <file>`) using `run_shell_command` to ensure there are no syntax errors before considering the task complete.

### Available Tools:
{self.tool_docs}
"""
