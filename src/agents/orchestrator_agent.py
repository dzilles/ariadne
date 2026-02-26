import logging
from src.agents.base_agent import BaseAgent
from src.tools.plane_client import PlaneInteraction
from src.tools.pm_tools import ProjectManagementAgentTools
from src.tools.file_tools import FileAgentTools
from src.tools.tool_wrapper import wrap_tools_with_error_handling

logger = logging.getLogger(__name__)

class OrchestratorAgent(BaseAgent):
    """
    Orchestrator Agent responsible for coordinating the workflow and high-level planning.
    """

    def __init__(self):
        super().__init__("ORCHESTRATOR_AGENT_API_KEY")

        try:
            self.client = PlaneInteraction(api_key=self.api_key)
            self.pm_tools = ProjectManagementAgentTools(self.client)
            self.file_tools = FileAgentTools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        self.tools = wrap_tools_with_error_handling([
            self.pm_tools.get_ticket_details,
            self.pm_tools.search_tickets,
            self.pm_tools.update_ticket,
            self.pm_tools.add_comment,
            self.file_tools.read_file,
            self.file_tools.list_files
        ])

        self.tool_docs = "\n".join([
            self.pm_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions()
        ])

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are the Orchestrator Agent.
Your goal is to coordinate the development lifecycle and ensure smooth handoffs between agents.

### Responsibilities:
1.  **Monitor:** Keep track of ticket status and overall project progress.
2.  **Assign:** Ensure tickets are assigned to the correct role/agent based on their current state.
3.  **Plan:** Assist in high-level sprint planning and backlog grooming.

### Available Tools:
{self.tool_docs}
"""