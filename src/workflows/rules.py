from typing import List, Optional
from pydantic import BaseModel
from src.interfaces.ticket_system import TicketStatus

class WorkflowRule(BaseModel):
    current_state: TicketStatus
    agent_name: str
    description: str
    allowed_actions: List[str]
    required_artifact_pattern: Optional[str] = None
    next_state: Optional[TicketStatus] = None
    gate_to_update: Optional[str] = None

# ==============================================================================
# ARIADNE V-MODEL WORKFLOW RULES
# ==============================================================================
# This list defines the Single Source of Truth for the autonomous lifecycle.
# It maps the Ticket Status -> The Agent that owns it -> The Expected Outcome.
# ==============================================================================

WORKFLOW_RULES: List[WorkflowRule] = [
    # 1. Backlog Refinement
    WorkflowRule(
        current_state=TicketStatus.BACKLOG,
        agent_name="Product Owner",
        description="Review new request, clarify ambiguities, and prepare for analysis.",
        allowed_actions=["update_description", "post_comment", "update_status"],
        next_state=TicketStatus.READY_FOR_ANALYSIS
    ),

    # 2. Requirements Analysis
    WorkflowRule(
        current_state=TicketStatus.READY_FOR_ANALYSIS,
        agent_name="Requirements",
        description="Analyze User Story and generate formal Requirement Specification.",
        allowed_actions=["read_file", "write_file", "git_commit", "add_artifact_link", "update_status"],
        required_artifact_pattern="docs/requirements/REQ-{id}.md",
        gate_to_update="analysis",
        next_state=TicketStatus.READY_FOR_DESIGN
    ),

    # 3. System Architecture
    WorkflowRule(
        current_state=TicketStatus.READY_FOR_DESIGN,
        agent_name="Architect",
        description="Review Requirements and generate Technical Design.",
        allowed_actions=["read_file", "write_file", "git_commit", "add_artifact_link", "update_status"],
        required_artifact_pattern="docs/design/DESIGN-{id}.md",
        gate_to_update="design",
        next_state=TicketStatus.READY_FOR_DEVELOPMENT
    ),

    # 4. Implementation
    WorkflowRule(
        current_state=TicketStatus.READY_FOR_DEVELOPMENT,
        agent_name="Developer",
        description="Implement the feature code based on the Technical Design.",
        allowed_actions=["read_file", "write_file", "git_commit", "update_status"],
        # No single artifact pattern for code, but implied output is source code
        next_state=TicketStatus.READY_FOR_TESTING
    ),

    # 5. Testing
    WorkflowRule(
        current_state=TicketStatus.READY_FOR_TESTING,
        agent_name="Tester",
        description="Write and execute automated tests against the implementation.",
        allowed_actions=["read_file", "write_file", "run_test_command", "git_commit", "update_status"],
        gate_to_update="test",
        next_state=TicketStatus.READY_FOR_QA
    ),

    # 6. Quality Assurance
    WorkflowRule(
        current_state=TicketStatus.READY_FOR_QA,
        agent_name="QA",
        description="Final process check and validation.",
        allowed_actions=["read_file", "update_status"],
        next_state=TicketStatus.DONE
    )
]

def get_rule_for_status(status: str) -> Optional[WorkflowRule]:
    """Retrieve the rule that applies to the given status."""
    # Normalize string to Enum if possible
    try:
        enum_status = TicketStatus(status)
        for rule in WORKFLOW_RULES:
            if rule.current_state == enum_status:
                return rule
    except ValueError:
        pass
    return None

def generate_instructions(rule: WorkflowRule, ticket_id: str) -> str:
    """
    Generates the dynamic constraint/instruction block for the Agent's system prompt.
    """
    instructions = [
        f"### CURRENT MISSION: {rule.current_state.value}",
        f"**Goal:** {rule.description}",
        f"**Allowed Actions:** {', '.join(rule.allowed_actions)}",
    ]
    
    if rule.required_artifact_pattern:
        artifact = rule.required_artifact_pattern.format(id=ticket_id)
        instructions.append(f"**Required Output:** You MUST create/update: `{artifact}`")
    
    if rule.gate_to_update:
        instructions.append(f"**Gate Check:** You MUST approve the '{rule.gate_to_update}' gate before moving forward.")
        
    if rule.next_state:
        instructions.append(f"**Success Criteria:** Move ticket status to '{rule.next_state.value}'.")
    
    return "\n".join(instructions)

