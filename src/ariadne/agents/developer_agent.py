import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.tools.git_tools import GitAgentTools
from src.ariadne.tools.shell_tools import ShellAgentTools
from src.ariadne.policies.registry import build_agent_tools, build_tool_docs
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class DeveloperAgent(BaseAgent):
    """
    Developer Agent responsible for Implementation and Coding.
    """

    def __init__(self, ticket_tools=None, file_tools=None, git_tools=None, shell_tools=None, agent_run_tools=None):
        super().__init__()

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_work_item_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
            self.git_tools = git_tools or DependencyRegistry.get_git_tools()
            self.shell_tools = shell_tools or DependencyRegistry.get_shell_tools()
            self.agent_run_tools = agent_run_tools or DependencyRegistry.get_agent_run_tools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # Map to expected tool names
        self.get_ticket_details = self.ticket_tools.get_work_item
        self.update_ticket = self.ticket_tools.update_status
        self.add_comment = self.ticket_tools.post_comment

        raw_tools = build_agent_tools(
            "Developer",
            [self.ticket_tools, self.file_tools, self.shell_tools, self.git_tools, self.agent_run_tools],
        )
        self.tools = wrap_tools_with_error_handling(raw_tools)

        self.tool_docs = build_tool_docs(raw_tools)

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

{self._completion_protocol()}

### Available Tools:
{self.tool_docs}
"""
