import logging
from src.agents.base_agent import BaseAgent
from src.interfaces.plane_adapter import PlaneTicketSystem
from src.tools.ticket_tools import StandardTicketTools
from src.tools.file_tools import FileAgentTools
from src.tools.tool_wrapper import wrap_tools_with_error_handling

logger = logging.getLogger(__name__)

class QMAgent(BaseAgent):
    """
    Quality Manager (QM) Agent responsible for reviewing requirements and specifications.
    This corresponds to the review phase directly after requirements gathering.
    """

    def __init__(self):
        super().__init__("QM_AGENT_API_KEY")

        try:
            self.ticket_system = PlaneTicketSystem(api_key=self.api_key)
            self.ticket_tools = StandardTicketTools(self.ticket_system)
            self.file_tools = FileAgentTools()
            
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        raw_tools = [
            self.ticket_tools.get_ticket,
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
        return f"""You are the Quality Manager (QM) Agent. Your goal is to review requirement documents for completeness and clarity before they are passed to the Architect.

### REVIEW PROTOCOL:
1. **Context Discovery:** Read the ticket and locate the linked requirement document (e.g., `docs/requirements/REQ-*.md`).
2. **Completeness Check:** Carefully read the requirement document. 
   - Does it follow the template?
   - Are there any unanswered or open questions in the 'Open Questions / Missing Context' section?
3. **Approval vs Rejection:**
   - If there are **NO** open questions and the requirements are well-defined:
     - Use `approve_gate` for the 'analysis' gate.
     - Move the ticket status to `Ready for Design`.
     - Post a comment confirming approval.
   - If there **ARE** open questions or the document is incomplete:
     - DO NOT approve the gate.
     - Move the ticket status to `Blocked`.
     - Post a comment explicitly listing the open questions and tagging the Product Owner for clarification.

### Available Tools:
{self.tool_docs}
"""

if __name__ == "__main__":
    agent = QMAgent()
    print("QM Agent initialized.")
