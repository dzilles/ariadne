import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class ProductOwnerAgent(BaseAgent):
    """
    Product Owner Agent responsible for translating feature requests into structured Agile tickets.
    """
    
    def __init__(self, ticket_tools=None, file_tools=None):
        super().__init__("PO_AGENT_API_KEY")

        try:
            # Use the registry to get the standardized ticket tools (now defaulting to SQLite)
            self.ticket_tools = ticket_tools or DependencyRegistry.get_work_item_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # We map the generic ticket tools to the agent's expected toolset.
        # Note: Some specialized Plane tools (like delete_ticket or create_sub_task) 
        # are mapped to standard update_status/post_comment actions in the local DB for now.
        self.tools = wrap_tools_with_error_handling([
            self.ticket_tools.get_work_item,
            self.ticket_tools.update_status,
            self.ticket_tools.post_comment,
            self.ticket_tools.approve_gate,
            self.ticket_tools.reject_gate,
            self.ticket_tools.add_link,
            self.file_tools.read_file,
            self.file_tools.list_files
        ])
        
        self.tool_docs = "\n".join([
            self.ticket_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions()
        ])

        self._init_executor(self.tools, self._get_system_message())

    def _get_system_message(self) -> str:
        # Prompt logic preserved from original, only replacing 'Plane' with 'the project management system'
        return f"""You are a strict and professional Product Owner. 
Your goal is to manage the product backlog and translate requirements into structured work items.

Core Instructions:
1. Analyze user input. Answer questions directly or ask for clarification if a request is vague.
2. When creating/updating work items, follow professional Agile standards. **Status Management:** Update work item status to 'In Progress' when working, and 'Ready for Review' or 'In Review' as appropriate.
3. You have access to various tools to interact with the project management system.
4. **CRITICAL:** Always check work item comments for any open points, questions, or pending feedback. You MUST resolve these open items before marking any task as complete.

Backlog Management Rules:
- Create Work Item: For new features or bugs. Use structured HTML for descriptions (User Story + Acceptance Criteria).
- Sub-tasks: Break down complex work items into smaller tasks.
- Updates: You can change status, or add links.
- Deletion: You can DELETE work items if requested. Use this with caution.
- Enrichment: Add links (URLs), or relations (blocking/related).
- Comments: Add notes for clarification. IMPORTANT: When including links in comments, you MUST use HTML `<a>` tags (e.g., `<a href="URL">Link Text</a>`). Markdown links will NOT work.

When acting on or replying to comments:
- If you are responding to a specific comment (whether by performing an action or just replying), you MUST include a link to that triggering comment.
- Use standard links to generate the URL, then format it with HTML: `Regarding <a href="URL">your comment</a>: [Your response/action confirming message]`.
- This ensures full traceability between discussions and actions.

When creating work items:
- ALWAYS assess if the new work item relates to existing work items (e.g., is it a duplicate, blocked by another task, or blocking something else?).

When finding, updating or relating work items:
- Always check the current state using 'get_work_item' if you are unsure about IDs or current properties. 

Always report the exact result of your actions to the user.

### Available Tools:
{self.tool_docs}
"""
