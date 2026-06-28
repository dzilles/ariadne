import logging
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.work_items.tools import StandardTicketTools
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)

class OrchestratorAgent(BaseAgent):
    """
    Orchestrator Agent responsible for coordinating the workflow and high-level planning.
    """

    def __init__(self, ticket_tools=None, file_tools=None):
        super().__init__("ORCHESTRATOR_AGENT_API_KEY")

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_ticket_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # Map to expected tool names
        self.get_ticket_details = self.ticket_tools.get_ticket
        self.update_ticket = self.ticket_tools.update_status
        self.add_comment = self.ticket_tools.post_comment

        self.tools = wrap_tools_with_error_handling([
            self.get_ticket_details,
            self.update_ticket,
            self.add_comment,
            self.file_tools.read_file,
            self.file_tools.list_files,
            self.delegate_to_agent
        ])

        self.tool_docs = "\n".join([
            self.ticket_tools.get_tool_descriptions(),
            self.file_tools.get_tool_descriptions(),
            "### Orchestration Tools",
            "* `delegate_to_agent(agent_name, ticket_id, task_description)`: Delegates a specific ticket to a specialized agent."
        ])

        self._init_executor(self.tools, self._get_system_message())

    def delegate_to_agent(self, agent_name: str, ticket_id: str, task_description: str) -> str:
        """
        Delegates a task to a specialized agent and automatically updates the ticket status.
        The Orchestrator MUST use this to move through the V-Model.
        
        Args:
            agent_name: Name of the agent (Requirements, Architect, Developer, Tester, QA)
            ticket_id: The ID of the ticket.
            task_description: Specific instructions for the agent.
        """
        from src.ariadne.ui.agent_adapter import AGENT_CLASSES
        from src.ariadne.workflows.context import set_active_ticket_id
        from src.ariadne.work_items.models import TicketStatus
        
        if agent_name not in AGENT_CLASSES:
            return f"Error: Unknown agent '{agent_name}'. Available: {list(AGENT_CLASSES.keys())}"

        # Status mapping for automatic ticket reopening/progression
        status_map = {
            "Requirements": TicketStatus.READY_FOR_ANALYSIS,
            "Architect": TicketStatus.READY_FOR_DESIGN,
            "Developer": TicketStatus.READY_FOR_DEVELOPMENT,
            "Tester": TicketStatus.READY_FOR_TESTING,
            "QA": TicketStatus.READY_FOR_QA
        }

        # Set the context for the JIT guard
        set_active_ticket_id(ticket_id)
        
        try:
            # 1. Ensure ticket is in the correct status for the agent
            if agent_name in status_map:
                target_status = status_map[agent_name]
                logger.info(f"Orchestrator: Ensuring ticket #{ticket_id} is in status '{target_status.value}' for {agent_name} agent.")
                # We update it to ensure it's not 'Done' or in a previous state
                self.update_ticket(ticket_id=ticket_id, status=target_status.value)
                self.add_comment(ticket_id=ticket_id, comment=f"Ariadne Orchestrator: Delegating task to {agent_name} agent. Moving ticket to {target_status.value}.")

            # 2. Instantiate and chat with agent
            agent_instance = AGENT_CLASSES[agent_name]()
            response = agent_instance.chat(f"Context: You are working on Ticket #{ticket_id}. Task: {task_description}")
            return f"[{agent_name} Response]:\n{response}"
        except Exception as e:
            return f"Error delegating to {agent_name}: {str(e)}"

    def _get_system_message(self) -> str:
        return f"""You are the Orchestrator Agent, the 'Scrum Master' of the Ariadne V-Model.
Your goal is to coordinate the development lifecycle with maximum efficiency and minimal token waste.

### SURGICAL DELEGATION PROTOCOL:
When using `delegate_to_agent`, you MUST structure your `task_description` as follows:
1. **Goal:** Clear statement of the desired outcome.
2. **Knowledge Summary:** Summarize what you already know (e.g., from comments or previous steps) so the agent doesn't have to re-discover it.
3. **Primary Manifests (Discovery-by-Query):** List the EXACT files or directories the agent should examine. 
    *   **Crucial:** If this is a refinement task (updating an existing requirement or design), you MUST discover the existing file path first. Do this by either checking the `Links` attached to the parent Epic/Ticket using `get_ticket_details`, or using `search_files` based on keywords. Do NOT assume the file is named after the ticket ID. Provide the discovered file path here.
    *   Tell them: "Your primary context is in [Files]. You should prioritize these. If you identify a dependency outside this list, you may explore it, but you MUST state your reasoning in your 'Thought'."
4. **Expected Artifact:** Define the expected outcome (e.g., "Updated docs/requirements/REQ-005.md and attached to the ticket via add_link").

### Responsibilities:
1. **Monitor:** Track ticket status and progress in the project management system.
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
