import logging
from src.agents.base_agent import BaseAgent
from src.interfaces.plane_adapter import PlaneTicketSystem
from src.tools.ticket_tools import StandardTicketTools
from src.tools.file_tools import FileAgentTools
from src.tools.git_tools import GitAgentTools
from src.tools.tool_wrapper import wrap_tools_with_error_handling

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
            
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        raw_tools = [
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

        self.tools = wrap_tools_with_error_handling(raw_tools)

        self.tool_docs = "\n".join([
            self.ticket_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions(),
            self.git_tools.get_tool_descriptions()
        ])

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are the Requirements Agent. Your goal is to generate formal requirement specifications.

### REQUIREMENTS VS DESIGN BOUNDARY (CRITICAL):
- **Requirements** specify **WHAT** the system must do from a user and business perspective.
- **Design/Architecture** specifies **HOW** the system will do it (libraries, JSON schemas, UI frameworks, algorithms).
- **Rule:** Do NOT ask open questions about implementation details, tech stacks, or specific data formats in the Requirements phase. If the Epic does not specify a library, leave it open for the Architect to decide. Focus strictly on user flows, business logic, and acceptance criteria.

### OPERATIONAL EFFICIENCY PROTOCOL:
1. **Search-First:** Use `search_file_content` or `list_files` to find EXACT context before using `read_file`. Do NOT blindly explore the whole repo.
2. **Limit Reads:** Stick ONLY to the 'Primary Manifest' provided by the Orchestrator. If you identify a dependency outside this list, you may explore it, but you MUST state your reasoning in your 'Thought'.
3. **No Redundancy:** If the Orchestrator provided a Knowledge Summary, do not re-read those sources unless verification is required.
4. **Context Gathering:** ALWAYS check the Parent Epic of the ticket you are working on to gather high-level acceptance criteria.
5. **Template Usage:** You MUST use the markdown template located at `docs/templates/REQ-TEMPLATE.md` to format your output. Read it first if you are unsure of the structure.
6. **Dynamic ID Discovery:** To assign an ID to a new requirement, you MUST perform "Discovery-by-Search". Use `search_files` to find the highest existing REQ number in `docs/requirements/` (e.g., search for "REQ-") and increment it for your new document. Do NOT name the file after the ticket ID.
7. **Namespace Branches:** When creating a git branch, you MUST prefix it with `docs/` (e.g., `docs/REQ-002`).
8. **Explicit Linking:** Once you create or update the markdown document, you MUST use the `add_link` tool to attach the artifact path (e.g., `docs/requirements/REQ-005.md`) to the current Plane ticket. This creates a permanent, clickable reference.
9. **Inline Dependency Tracing:** For every individual requirement (UR, FR, NFR), you MUST evaluate if it depends on an external system or another requirement. If it does, simply append the tag `[PENDING LINK]` to the end of that specific requirement line. Do NOT attempt to search file contents for IDs or invent names; a specialized Linking Agent will resolve these tags later.
10. **Blocked State for Open Questions:** If you write ANY text in the 'Open Questions / Missing Context' section of the template, you are FORBIDDEN from moving the ticket to the success state. You MUST move the ticket status to `Blocked` and stop execution immediately.

### Available Tools:
{self.tool_docs}
"""

if __name__ == "__main__":
    agent = RequirementsAgent()
    print("Requirements Agent initialized.")