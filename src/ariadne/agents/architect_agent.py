import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.tools.git_tools import GitAgentTools
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class ArchitectAgent(BaseAgent):
    """
    Architect Agent responsible for System Design and Architecture.
    """

    def __init__(self, ticket_tools=None, file_tools=None, git_tools=None):
        super().__init__("ARCHITECT_AGENT_API_KEY")

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_work_item_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
            self.git_tools = git_tools or DependencyRegistry.get_git_tools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # We keep the function names that the agent might expect but map them to the new tools
        self.get_ticket_details = self.ticket_tools.get_work_item
        self.update_ticket = self.ticket_tools.update_status
        self.add_comment = self.ticket_tools.post_comment
        self.add_link = self.ticket_tools.add_link

        self.tools = wrap_tools_with_error_handling([
            self.get_ticket_details,
            self.update_ticket,
            self.add_comment,
            self.add_link,
            self.ticket_tools.approve_gate,
            self.ticket_tools.reject_gate,
            self.file_tools.read_file,
            self.file_tools.list_files,
            self.file_tools.search_files,
            self.file_tools.write_file,
            self.git_tools.get_status,
            self.git_tools.get_current_branch,
            self.git_tools.create_branch,
            self.git_tools.add_files,
            self.git_tools.commit_changes
        ])

        self.tool_docs = "\n".join([
            self.ticket_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions(),
            self.git_tools.get_tool_descriptions()
        ])

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

### Available Tools:
{self.tool_docs}
"""
