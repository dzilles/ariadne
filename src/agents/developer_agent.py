import logging
from src.agents.base_agent import BaseAgent
from src.tools.plane_client import PlaneInteraction
from src.tools.pm_tools import ProjectManagementAgentTools
from src.tools.file_tools import FileAgentTools
from src.tools.git_tools import GitAgentTools
from src.tools.shell_tools import ShellAgentTools
from src.tools.tool_wrapper import wrap_tools_with_error_handling

logger = logging.getLogger(__name__)

class DeveloperAgent(BaseAgent):
    """
    Developer Agent responsible for Implementation and Coding.
    """

    def __init__(self):
        super().__init__("DEVELOPER_AGENT_API_KEY")

        try:
            self.client = PlaneInteraction(api_key=self.api_key)
            self.pm_tools = ProjectManagementAgentTools(self.client)
            self.file_tools = FileAgentTools()
            self.git_tools = GitAgentTools()
            self.shell_tools = ShellAgentTools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        self.tools = wrap_tools_with_error_handling([
            self.pm_tools.get_ticket_details,
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
            self.pm_tools.add_comment,
            self.pm_tools.update_ticket,
            self.pm_tools.search_tickets
        ])

        self.tool_docs = "\n".join([
            self.pm_tools.get_tool_descriptions(),
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
4.  **Update Tickets:** Keep the ticket status updated as you work.
5.  **Code-Level Traceability:** When modifying functions/classes, you MUST include a traceability tag in the docstring or comment: `Implementation of ARCH-XXX. Fulfills REQ-XXX.`
6.  **Verify:** After making code changes, ALWAYS run simple developer tests (e.g., `python -m py_compile <file>`) using `run_shell_command` to ensure there are no syntax errors before considering the task complete.

### Available Tools:
{self.tool_docs}
"""