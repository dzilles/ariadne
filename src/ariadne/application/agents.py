"""Agent registry for the Ariadne application layer.

The registry intentionally avoids importing concrete agent modules until an
agent class is requested. Importing those modules initializes LLM/settings
dependencies, which should not happen when the UI only needs display metadata.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from importlib import import_module
from typing import Callable


_AGENT_SPECS = {
    "Orchestrator": (
        "src.ariadne.agents.orchestrator_agent",
        "OrchestratorAgent",
        "Manages backlog and coordinates the overall workflow",
    ),
    "Requirements": (
        "src.ariadne.agents.requirements_agent",
        "RequirementsAgent",
        "Refines tickets into detailed requirement documents",
    ),
    "QM": (
        "src.ariadne.agents.qm_agent",
        "QMAgent",
        "Reviews requirement documents for completeness and clarity",
    ),
    "Architect": (
        "src.ariadne.agents.architect_agent",
        "ArchitectAgent",
        "Designs system architecture and technical specifications",
    ),
    "Developer": (
        "src.ariadne.agents.developer_agent",
        "DeveloperAgent",
        "Implements features and fixes bugs based on designs",
    ),
    "Tester": (
        "src.ariadne.agents.tester_agent",
        "TesterAgent",
        "Writes and executes automated tests",
    ),
    "QA": (
        "src.ariadne.agents.qa_agent",
        "QualityAssuranceAgent",
        "Reviews code and validates adherence to quality standards",
    ),
}


class LazyAgentRegistry(Mapping[str, Callable]):
    """Mapping that imports concrete agent classes on demand."""

    def __init__(self) -> None:
        self._cache: dict[str, Callable] = {}

    def __getitem__(self, name: str) -> Callable:
        if name not in _AGENT_SPECS:
            raise KeyError(name)
        if name not in self._cache:
            module_name, class_name, _description = _AGENT_SPECS[name]
            module = import_module(module_name)
            self._cache[name] = getattr(module, class_name)
        return self._cache[name]

    def __iter__(self) -> Iterator[str]:
        return iter(_AGENT_SPECS)

    def __len__(self) -> int:
        return len(_AGENT_SPECS)


AGENT_CLASSES = LazyAgentRegistry()

AGENT_DESCRIPTIONS = {
    name: description
    for name, (_module_name, _class_name, description) in _AGENT_SPECS.items()
}


def get_agent_names() -> list[str]:
    """Get list of available agent names."""
    return list(_AGENT_SPECS.keys())
