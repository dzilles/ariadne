import logging
from src.agents.base_agent import BaseAgent
from src.tools.plane_client import PlaneInteraction
from src.tools.pm_tools import ProjectManagementAgentTools
from src.tools.file_tools import FileAgentTools
from src.tools.tool_wrapper import wrap_tools_with_error_handling

logger = logging.getLogger(__name__)

class ArchitectAgent(BaseAgent):
    """
    Architect Agent responsible for System Design and Architecture.
    """

    def __init__(self):
        super().__init__("ARCHITECT_AGENT_API_KEY")

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
            self.pm_tools.search_tickets
        ])

        self.tool_docs = "\n".join([
            self.pm_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions()
        ])

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are a Systems Architect.
Your goal is to design the system architecture and ensure technical feasibility.

### Responsibilities:
1.  **Analyze Requirements:** Review functional requirements and specifications.
2.  **Design Architecture:** specific high-level designs, data models, and component interactions.
3.  **Document:** Create or update design documents (DESIGN-*.md).
4.  **Review:** Review code and designs for architectural consistency.

### Available Tools:
{self.tool_docs}
"""