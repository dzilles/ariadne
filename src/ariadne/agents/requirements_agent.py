import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.policies.registry import build_agent_tools, build_tool_docs
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)


class RequirementsAgent(BaseAgent):
    """
    Requirements Agent responsible for refining tickets into detailed Requirement Documents.
    This corresponds to the 'Requirement Gathering' phase of the V-Model.
    """

    def __init__(
        self, ticket_tools=None, file_tools=None, git_tools=None, agent_run_tools=None
    ):
        super().__init__()

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_work_item_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
            self.git_tools = git_tools or DependencyRegistry.get_git_tools()
            self.agent_run_tools = (
                agent_run_tools or DependencyRegistry.get_agent_run_tools()
            )

        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        raw_tools = build_agent_tools(
            "Requirements",
            [self.agent_run_tools, self.ticket_tools, self.file_tools, self.git_tools],
        )
        self.tools = wrap_tools_with_error_handling(
            raw_tools, agent_name="Requirements"
        )

        self.tool_docs = build_tool_docs(raw_tools)

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are the Requirements Agent. Your goal is to generate formal requirement specifications.

### REQUIREMENTS VS DESIGN BOUNDARY (CRITICAL):
- **Requirements** specify **WHAT** the system must do from a user and business perspective.
- **Design/Architecture** specifies **HOW** the system will do it (libraries, JSON schemas, UI frameworks, algorithms).
- **Rule:** Do NOT ask open questions about implementation details, tech stacks, or specific data formats in the Requirements phase. If the Epic does not specify a library, leave it open for the Architect to decide. Focus strictly on user flows, business logic, and acceptance criteria.

### OPERATIONAL EFFICIENCY PROTOCOL:
1. **Search-First:** Use `search_files` or `list_files` to find exact context before using `read_file`. Do not blindly explore the whole repository.
2. **Limit Reads:** Prioritize the primary files provided by the Orchestrator. Explore outside that list only when the requirement depends on additional context, and record that dependency in the completion details.
3. **No Redundancy:** If the Orchestrator provided a Knowledge Summary, do not re-read those sources unless verification is required.
4. **Context Gathering:** Use the delegated context bundle and current work item as the authoritative source for high-level acceptance criteria.
5. **Template Usage:** You MUST use the markdown template located at `docs/templates/REQ-TEMPLATE.md` to format your output. Read it first if you are unsure of the structure.
6. **Dynamic ID Discovery:** To assign an ID to a new requirement, you MUST perform "Discovery-by-Search". Use `search_files` to find the highest existing REQ number in `docs/requirements/` (e.g., search for "REQ-") and increment it for your new document. Do NOT name the file after the ticket ID.
7. **Namespace Branches:** When creating a git branch, you MUST prefix it with `docs/` (e.g., `docs/REQ-002`).
8. **Artifact Reporting:** Include each created or updated requirement document in the `artifacts` field of `return_to_orchestrator`. The coordinator creates the durable work-item link.
9. **Inline Dependency Tracing:** For every individual requirement (UR, FR, NFR), you MUST evaluate if it depends on an external system or another requirement. If it does, simply append the tag `[PENDING LINK]` to the end of that specific requirement line. Do NOT attempt to search file contents for IDs or invent names; a specialized Linking Agent will resolve these tags later.
10. **Open Questions:** If the document contains any unresolved item in 'Open Questions / Missing Context', return `FAILED` with each question in `blockers`. Do not change the work-item status yourself.

{self._completion_protocol()}

### Available Tools:
{self.tool_docs}
"""
