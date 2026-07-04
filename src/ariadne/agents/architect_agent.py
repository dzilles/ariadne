import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.tools.git_tools import GitAgentTools
from src.ariadne.tools.shell_tools import ShellAgentTools
from src.ariadne.policies.registry import build_agent_tools, build_tool_docs
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class ArchitectAgent(BaseAgent):
    """
    Architect Agent responsible for System Design and Architecture.
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

        # We keep the function names that the agent might expect but map them to the new tools
        self.get_ticket_details = self.ticket_tools.get_work_item
        self.update_ticket = self.ticket_tools.update_status
        self.add_comment = self.ticket_tools.post_comment
        self.add_link = self.ticket_tools.add_link

        raw_tools = build_agent_tools(
            "Architect",
            [self.agent_run_tools, self.ticket_tools, self.file_tools, self.shell_tools, self.git_tools],
        )
        self.tools = wrap_tools_with_error_handling(raw_tools)

        self.tool_docs = build_tool_docs(raw_tools)

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        return f"""You are the Architect Agent. Your goal is to design system architectures.

### ARCHITECTURAL REASONING PROTOCOL (MANDATORY):
You MUST begin every response with a `<thought>` block. Before calling any tools or writing the final Markdown document, your internal analysis MUST be extensive. You MUST explicitly address:
1. **Thread Safety Audit:** How will the UI stay responsive while a tool blocks? (e.g., specify `threading.Lock` or `queue.Queue` usage).
2. **Path Discovery:** You are FORBIDDEN from using `[PENDING LINK]` for any system that already exists in the repo. Use `search_file_content` to find real paths (e.g., for `tool_wrapper.py`).
3. **Developer Hand-off:** Explicitly ask: "How will a Developer Agent break this?" and then add a specific constraint to the doc to prevent it.
4. **Schema Completeness:** Every class/model mentioned MUST have at least 3-5 specific fields and types defined.

### OPERATIONAL EFFICIENCY PROTOCOL:
1. **Context Gathering:** ALWAYS check the Parent Epic of the ticket you are working on to gather high-level acceptance criteria.
2. **Requirement Review:** You MUST find and read the Requirement artifact (e.g., `docs/requirements/REQ-001.md`) generated in the previous phase to ensure architectural alignment.
3. **Template Usage:** You MUST use the markdown template located at `docs/templates/ARCH-TEMPLATE.md` to format your output. Read it first if you are unsure of the structure.
4. **Namespace Branches:** When creating a git branch, you MUST prefix it with `docs/` (e.g., `docs/ARCH-002`).
5. **Visual Documentation (MANDATORY):** You MUST include at least one Mermaid.js diagram (e.g., `graph TD`, `sequenceDiagram`) in every architecture document to visualize component interactions.
6. **Data Schema Rigor:** For every Data Model listed, you MUST define its primary fields and their types (e.g. using a list or a pseudo-Pydantic block).
7. **Explicit Linking:** Once you create or update the markdown document, you MUST use the `add_link` tool to attach the artifact path (e.g., `docs/design/ARCH-005.md`) to the current ticket. This creates a permanent, clickable reference.

{self._completion_protocol()}

### Available Tools:
{self.tool_docs}
"""
