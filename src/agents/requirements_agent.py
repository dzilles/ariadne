import logging
from src.agents.base_agent import BaseAgent
from src.interfaces.plane_adapter import PlaneTicketSystem
from src.tools.ticket_tools import StandardTicketTools
from src.tools.file_tools import FileAgentTools
from src.tools.git_tools import GitAgentTools
from src.tools.tool_wrapper import wrap_tools_with_error_handling
from src.workflows.enforcement import ToolGuard

logger = logging.getLogger(__name__)

class RequirementsAgent(BaseAgent):
    """
    Requirements Agent responsible for refining Plane tickets into detailed Requirement Documents.
    This corresponds to the 'Requirement Gathering' phase of the V-Model.
    """

    def __init__(self):
        super().__init__("REQUIREMENTS_AGENT_API_KEY")

        try:
            self.ticket_system = PlaneTicketSystem(api_key=self.api_key)
            self.ticket_tools = StandardTicketTools(self.ticket_system)
            self.file_tools = FileAgentTools()
            self.git_tools = GitAgentTools()
            
            self.guard = ToolGuard(self.ticket_system, agent_name="Requirements")
            
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        raw_tools = [
            self.guard.activate_ticket,
            self.ticket_tools.get_ticket,
            self.ticket_tools.update_status,
            self.ticket_tools.post_comment,
            self.ticket_tools.approve_gate,
            self.ticket_tools.reject_gate,
            self.ticket_tools.add_link,
            self.file_tools.read_file,
            self.file_tools.list_files,
            self.file_tools.write_file,
            self.file_tools.search_files,
            self.git_tools.get_status,
            self.git_tools.get_current_branch,
            self.git_tools.create_branch,
            self.git_tools.add_files,
            self.git_tools.commit_changes
        ]

        self.tools = wrap_tools_with_error_handling(self.guard.wrap_tools(raw_tools))

        self.tool_docs = "\n".join([
            "### Core Workflow Tool",
            "* `activate_ticket(ticket_id)`: **MUST CALL FIRST**. Locks context to a ticket and validates rules.",
            self.ticket_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions(),
            self.git_tools.get_tool_descriptions()
        ])

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are the Requirements Agent in the Ariadne V-Model lifecycle.

### CRITICAL PROTOCOL:
1.  **Activate First:** You cannot perform ANY action (writing files, committing code) until you successfully call `activate_ticket(ticket_id)`.
2.  **Verify Rules:** The `activate_ticket` tool will tell you if you are allowed to work. If it fails (e.g. "Access Denied"), you must stop and inform the user.
3.  **Follow Instructions:** Once activated, the system will provide you with specific instructions (Mission, Allowed Actions, Required Outputs) for that ticket. Follow them precisely.

### Workflow:
1.  User says "Work on #25".
2.  You call `activate_ticket("25")`.
3.  If successful, proceed with the instructions provided in the tool output.
    *   Typically: Read User Story -> Draft REQ-*.md -> Link Artifact -> Approve Gate.

### Available Tools:
{self.tool_docs}
"""

if __name__ == "__main__":
    agent = RequirementsAgent()
    print("Requirements Agent initialized.")
