import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.policies.registry import build_agent_tools, build_tool_docs
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)


class ArchitectAgent(BaseAgent):
    """
    Architect Agent responsible for System Design and Architecture.
    """

    def __init__(
        self,
        ticket_tools=None,
        file_tools=None,
        git_tools=None,
        shell_tools=None,
        agent_run_tools=None,
    ):
        super().__init__()

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_work_item_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
            self.git_tools = git_tools or DependencyRegistry.get_git_tools()
            self.shell_tools = shell_tools or DependencyRegistry.get_shell_tools()
            self.agent_run_tools = (
                agent_run_tools or DependencyRegistry.get_agent_run_tools()
            )
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        raw_tools = build_agent_tools(
            "Architect",
            [
                self.agent_run_tools,
                self.ticket_tools,
                self.file_tools,
                self.shell_tools,
                self.git_tools,
            ],
        )
        self.tools = wrap_tools_with_error_handling(raw_tools, agent_name="Architect")

        self.tool_docs = build_tool_docs(raw_tools)

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are the Architect Agent. Your goal is to design system architectures.

### ARCHITECTURAL RIGOR:
1. **Concurrency Audit:** Describe responsiveness, synchronization, and failure handling when the design introduces blocking or concurrent work.
2. **Path Discovery:** Use `search_files` to identify existing repository components and cite their real paths in the design.
3. **Implementation Constraints:** Record concrete invariants and edge cases the Developer must preserve.
4. **Schema Completeness:** Define the relevant fields and types for every proposed data model.

### OPERATIONAL EFFICIENCY PROTOCOL:
1. **Context Gathering:** Use the delegated context bundle and current work item for high-level acceptance criteria.
2. **Requirement Review:** You MUST find and read the Requirement artifact (e.g., `docs/requirements/REQ-001.md`) generated in the previous phase to ensure architectural alignment.
3. **Template Usage:** You MUST use the markdown template located at `docs/templates/ARCH-TEMPLATE.md` to format your output. Read it first if you are unsure of the structure.
4. **Namespace Branches:** When creating a git branch, you MUST prefix it with `docs/` (e.g., `docs/ARCH-002`).
5. **Visual Documentation (MANDATORY):** You MUST include at least one Mermaid.js diagram (e.g., `graph TD`, `sequenceDiagram`) in every architecture document to visualize component interactions.
6. **Data Schema Rigor:** For every Data Model listed, you MUST define its primary fields and their types (e.g. using a list or a pseudo-Pydantic block).
7. **Artifact Reporting:** Include each created or updated design document in the `artifacts` field of `return_to_orchestrator`. The coordinator creates the durable work-item link.
8. **Design Gate:** On success, return an `Approved` `gate_decision` for the design gate. Return `FAILED` with a rejected decision when the design remains incomplete.

{self._completion_protocol()}

### Available Tools:
{self.tool_docs}
"""
