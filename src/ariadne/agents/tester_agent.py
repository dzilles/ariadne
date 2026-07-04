import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.tools.git_tools import GitAgentTools
from src.ariadne.tools.shell_tools import ShellAgentTools
from src.ariadne.policies.registry import build_agent_tools, build_tool_docs
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class TesterAgent(BaseAgent):
    """
    Tester Agent responsible for writing and executing tests.
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
            "Tester",
            [self.ticket_tools, self.file_tools, self.shell_tools, self.git_tools, self.agent_run_tools],
        )
        self.tools = wrap_tools_with_error_handling(raw_tools)

        self.tool_docs = build_tool_docs(raw_tools)

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are a Software Tester.
Your goal is to write comprehensive tests for the software.

### Responsibilities:
1.  **Write Tests:** Create unit, integration, and system tests based on requirements and code.
2.  **Ensure Coverage:** Aim for high code coverage and test edge cases.
3.  **Validate:** Ensure tests pass locally before committing.
4.  **Document:** Document test cases and instructions.

{self._completion_protocol()}

### Available Tools:
{self.tool_docs}
"""
