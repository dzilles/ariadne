import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.policies.registry import build_agent_tools, build_tool_docs
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class QualityAssuranceAgent(BaseAgent):
    """
    QA Agent responsible for Testing and Validation.
    """

    def __init__(self, ticket_tools=None, file_tools=None):
        super().__init__()

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_work_item_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # Map to expected tool names
        self.get_ticket_details = self.ticket_tools.get_work_item
        self.update_ticket = self.ticket_tools.update_status
        self.add_comment = self.ticket_tools.post_comment

        raw_tools = build_agent_tools("QA", [self.ticket_tools, self.file_tools])
        self.tools = wrap_tools_with_error_handling(raw_tools)

        self.tool_docs = build_tool_docs(raw_tools)

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
