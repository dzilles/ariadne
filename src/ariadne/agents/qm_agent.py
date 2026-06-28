import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class QMAgent(BaseAgent):
    """
    Quality Manager (QM) Agent responsible for reviewing artifacts across the V-Model lifecycle.
    It checks requirements, architecture, and other documents for completeness and open questions.
    """

    def __init__(self, ticket_tools=None, file_tools=None):
        super().__init__("QM_AGENT_API_KEY")

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_work_item_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
            
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        raw_tools = [
            self.ticket_tools.get_work_item,
            self.ticket_tools.update_status,
            self.ticket_tools.post_comment,
            self.ticket_tools.approve_gate,
            self.ticket_tools.reject_gate,
            self.file_tools.read_file,
            self.file_tools.list_files,
            self.file_tools.search_files
        ]

        self.tools = wrap_tools_with_error_handling(raw_tools)

        self.tool_docs = "\n".join([
            self.ticket_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions()
        ])

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are the Quality Manager (QM) Agent. Your goal is to review generated artifacts (Requirements, Architecture, etc.) for completeness and clarity before they proceed to the next phase in the V-Model.

### REVIEW PROTOCOL:
1. **Context Discovery:** Read the current ticket and locate the linked artifact document (e.g., `docs/requirements/REQ-*.md` or `docs/design/ARCH-*.md`).
2. **Completeness Check:** Carefully read the artifact document. 
   - Does it adhere to its respective template in `docs/templates/`?
   - Are there any unanswered questions, "TBD"s, or open points in the 'Open Questions / Missing Context' section?
3. **Approval vs Rejection:**
   - If there are **NO** open questions and the artifact is complete:
     - Use `approve_gate` for the specific gate mentioned in your CURRENT MISSION instructions.
     - Move the ticket status to the 'Success Criteria' state mentioned in your CURRENT MISSION instructions.
     - Post a comment confirming your approval.
   - If there **ARE** open questions, "TBD"s, or the document is incomplete:
     - DO NOT approve the gate.
     - Move the ticket status to `Blocked`.
     - Post a comment explicitly listing the open questions and tagging the responsible party for clarification.

### Available Tools:
{self.tool_docs}
"""

if __name__ == "__main__":
    agent = QMAgent()
    print("QM Agent initialized.")