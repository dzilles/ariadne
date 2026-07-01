import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class OrchestratorAgent(BaseAgent):
    """
    Orchestrator Agent responsible for coordinating the workflow and high-level planning.
    """

    def __init__(self, ticket_tools=None, file_tools=None):
        super().__init__()

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_work_item_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # Map to expected tool names
        self.get_ticket_details = self.ticket_tools.get_work_item
        self.update_work_item = self.ticket_tools.update_status
        self.add_comment = self.ticket_tools.post_comment

        self.tools = wrap_tools_with_error_handling([
            self.ticket_tools.list_work_items,
            self.get_ticket_details,
            self.ticket_tools.get_work_item_info,
            self.ticket_tools.activate_work_item,
            self.update_work_item,
            self.add_comment,
            self.ticket_tools.approve_gate,
            self.ticket_tools.reject_gate,
            self.ticket_tools.add_link,
            self.ticket_tools.append_shared_context,
            self.ticket_tools.update_git_metadata,
            self.file_tools.read_file,
            self.file_tools.list_files,
            self.delegate_to_agent
        ])

        self.tool_docs = "\n".join([
            self.ticket_tools.get_tool_descriptions(include_context_writer=True),
            self.file_tools.get_tool_descriptions(),
            "### Orchestration Tools",
            "* `delegate_to_agent(agent_name, work_item_id, task_description)`: Delegates a specific work item to a specialized agent."
        ])

        self._init_executor(self.tools, self._get_system_message())

    def delegate_to_agent(self, agent_name: str, work_item_id: str, task_description: str) -> str:
        """
        Delegates a task to a specialized agent and automatically updates the work item status.
        The Orchestrator MUST use this to move through the V-Model.
        
        Args:
            agent_name: Name of the agent (Requirements, Architect, Developer, Tester, QA)
            work_item_id: The ID of the work item.
            task_description: Specific instructions for the agent.
        """
        from src.ariadne.ui.agent_adapter import AGENT_CLASSES
        from src.ariadne.runtime.context import set_active_work_item_id
        from src.ariadne.work_items.models import WorkItemStatus
        
        if agent_name not in AGENT_CLASSES:
            return f"Error: Unknown agent '{agent_name}'. Available: {list(AGENT_CLASSES.keys())}"

        # Status mapping for automatic work item reopening/progression
        status_map = {
            "Requirements": WorkItemStatus.READY_FOR_ANALYSIS,
            "Architect": WorkItemStatus.READY_FOR_DESIGN,
            "Developer": WorkItemStatus.READY_FOR_DEVELOPMENT,
            "Tester": WorkItemStatus.READY_FOR_TESTING,
            "QA": WorkItemStatus.READY_FOR_QA
        }

        # Set the context for the JIT guard
        set_active_work_item_id(work_item_id)
        
        try:
            # 1. Ensure work item is in the correct status for the agent
            if agent_name in status_map:
                target_status = status_map[agent_name]
                logger.info(f"Orchestrator: Ensuring work item #{work_item_id} is in status '{target_status.value}' for {agent_name} agent.")
                # We update it to ensure it's not 'Done' or in a previous state
                self.update_work_item(work_item_id=work_item_id, status=target_status.value)
                self.add_comment(work_item_id=work_item_id, comment=f"Ariadne Orchestrator: Delegating task to {agent_name} agent. Moving work item to {target_status.value}.")

            # 2. Instantiate and chat with agent
            agent_instance = AGENT_CLASSES[agent_name]()
            response = agent_instance.chat(
                self._build_delegation_prompt(agent_name, work_item_id, task_description)
            )
            self._append_agent_handoff_context(work_item_id, agent_name, response)
            return f"[{agent_name} Response]:\n{response}"
        except Exception as e:
            return f"Error delegating to {agent_name}: {str(e)}"

    def _build_delegation_prompt(self, agent_name: str, work_item_id: str, task_description: str) -> str:
        return f"""Context: You are working on work item #{work_item_id}.

Task:
{task_description}

Before you finish, you MUST:
1. Check the current work item with `get_work_item` so your answer reflects the latest status, shared context, artifacts, and comments.
2. Complete the delegated task as far as your role allows.
3. Return a final section named `Context update for Orchestrator` with concise handoff context: decisions made, files changed or inspected, relevant artifacts, relevant commit hashes, blockers, and assumptions.
4. State whether your delegated task is finished.
5. If the work is not finished, state exactly which next agent should be called and why.

Do not call `append_shared_context`. Only the Orchestrator writes shared context after reviewing your response.
"""

    def _append_agent_handoff_context(self, work_item_id: str, agent_name: str, response: str) -> None:
        context = (
            f"Delegated agent: {agent_name}\n"
            "The following response was returned after the agent was instructed to check "
            "the work item and provide a context update for the Orchestrator.\n\n"
            f"{response}"
        )
        result = self.ticket_tools.append_shared_context(work_item_id, agent_name, context)
        logger.info("Shared context append result for work item #%s: %s", work_item_id, result)

    def _get_system_message(self) -> str:
        return f"""You are the Orchestrator Agent for the Ariadne V-Model.
Your goal is to manage the backlog, translate user requests into structured work items, and coordinate the development lifecycle with maximum efficiency and minimal token waste.

### Backlog Management
1. Analyze user input. Answer questions directly or ask for clarification if a request is vague.
2. When creating or updating work items, follow professional Agile standards.
3. Always check work item comments for open points, questions, or pending feedback before marking work complete.
4. For new features or bugs, structure descriptions with a user story, acceptance criteria, technical context, and traceability where applicable.
5. When acting on existing work items, check the current state with `get_work_item` if IDs, status, comments, artifacts, or ownership are unclear.
6. Use `list_work_items` to discover available work items.
7. Use `activate_work_item` when the user wants to work with a work item in this conversation but has not asked you to delegate it to another agent.
8. Always report the exact result of your actions to the user.

### SURGICAL DELEGATION PROTOCOL:
When using `delegate_to_agent`, you MUST structure your `task_description` as follows:
1. **Goal:** Clear statement of the desired outcome.
2. **Knowledge Summary:** Summarize what you already know (e.g., from comments or previous steps) so the agent doesn't have to re-discover it.
3. **Primary Manifests (Discovery-by-Query):** List the EXACT files or directories the agent should examine. 
    *   **Crucial:** If this is a refinement task (updating an existing requirement or design), you MUST discover the existing file path first. Do this by either checking the `Links` attached to the parent work item using `get_work_item`, or using `search_files` based on keywords. Do NOT assume the file is named after the work item ID. Provide the discovered file path here.
    *   Tell them: "Your primary context is in [Files]. You should prioritize these. If you identify a dependency outside this list, you may explore it, but you MUST state your reasoning in your 'Thought'."
4. **Expected Artifact:** Define the expected outcome (e.g., "Updated docs/requirements/REQ-005.md and attached to the work item via add_link").

### Responsibilities:
1. **Monitor:** Track work item status and progress in the project management system.
2. **Delegate:** Sequential dispatch: REQ -> ARCH -> DEV -> TEST -> QA.
3. **Validate:** Ensure agents return [SUCCESS] and produce the required artifacts.
4. **Escalations:** If an agent is blocked or hits a recursion limit, analyze the failure and provide narrower instructions.

### V-Model Sequence:
- [REQ] Requirements Agent (Output: docs/requirements/REQ-*.md)
- [ARCH] Architect Agent (Output: docs/design/ARCH-*.md)
- [DEV] Developer Agent (Output: Source Code)
- [TEST] Tester Agent (Output: tests/*.py)
- [QA] QA Agent (Output: Review Labels/Comments)

### Available Tools:
{self.tool_docs}
"""
