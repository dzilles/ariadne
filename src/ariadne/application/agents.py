"""Agent registry for the Ariadne application layer."""

from src.ariadne.agents.architect_agent import ArchitectAgent
from src.ariadne.agents.developer_agent import DeveloperAgent
from src.ariadne.agents.orchestrator_agent import OrchestratorAgent
from src.ariadne.agents.qa_agent import QualityAssuranceAgent
from src.ariadne.agents.qm_agent import QMAgent
from src.ariadne.agents.requirements_agent import RequirementsAgent
from src.ariadne.agents.tester_agent import TesterAgent


AGENT_CLASSES = {
    "Orchestrator": OrchestratorAgent,
    "Requirements": RequirementsAgent,
    "QM": QMAgent,
    "Architect": ArchitectAgent,
    "Developer": DeveloperAgent,
    "Tester": TesterAgent,
    "QA": QualityAssuranceAgent,
}

AGENT_DESCRIPTIONS = {
    "Orchestrator": "Manages backlog and coordinates the overall workflow",
    "Requirements": "Refines tickets into detailed requirement documents",
    "QM": "Reviews requirement documents for completeness and clarity",
    "Architect": "Designs system architecture and technical specifications",
    "Developer": "Implements features and fixes bugs based on designs",
    "Tester": "Writes and executes automated tests",
    "QA": "Reviews code and validates adherence to quality standards",
}


def get_agent_names() -> list[str]:
    """Get list of available agent names."""
    return list(AGENT_CLASSES.keys())
