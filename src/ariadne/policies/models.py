"""Typed policy models for configurable tool access."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PolicyCheck = Literal[
    "user_permission",
    "work_item_state",
    "work_item_transition",
    "work_item_field",
]


class ToolPolicy(BaseModel):
    """Policy attached to a tool name."""

    checks: list[PolicyCheck] = Field(default_factory=list)
    field_requirements: list[dict[str, Any]] = Field(default_factory=list)
    return_direct: bool = False
    coordinator_only: bool = False


class AgentPolicy(BaseModel):
    """Tools and prompt metadata for one agent."""

    prompt: str | None = None
    tools: list[str] = Field(default_factory=list)


class WorkflowToolPolicy(BaseModel):
    """Workflow-specific overrides for one tool in one work item state."""

    allowed_targets: list[str] = Field(default_factory=list)
    field_requirements: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowStatePolicy(BaseModel):
    """Policy for a single work item state."""

    owner: str | None = None
    allowed_tools: dict[str, WorkflowToolPolicy] = Field(default_factory=dict)
    next_state: str | None = None
    required_artifact_pattern: str | None = None
    gate_to_update: str | None = None
    entry_required_artifact_patterns: list[str] = Field(default_factory=list)
    entry_required_gates: list[str] = Field(default_factory=list)
    requires_clean_worktree: bool = False
    requires_verification: bool = False


class AgentToolPolicy(BaseModel):
    """Full policy document."""

    tools: dict[str, ToolPolicy] = Field(default_factory=dict)
    agents: dict[str, AgentPolicy] = Field(default_factory=dict)
    workflow: dict[str, WorkflowStatePolicy] = Field(default_factory=dict)
