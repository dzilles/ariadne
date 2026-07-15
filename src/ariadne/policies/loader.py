"""Load and validate agent tool policies."""

from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from typing import Any

from pydantic import ValidationError

from .defaults import DEFAULT_POLICY
from .models import AgentToolPolicy


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _workflow_defaults() -> dict[str, Any]:
    from src.ariadne.workflows.rules import WORKFLOW_RULES

    workflow = {}
    for rule in WORKFLOW_RULES:
        allowed_tools = {tool: {} for tool in rule.allowed_actions}
        if rule.next_state:
            allowed_tools.setdefault("update_status", {})
            allowed_tools["update_status"]["allowed_targets"] = [
                rule.next_state.value,
                "Blocked",
            ]
        workflow[rule.current_state.value] = {
            "owner": rule.agent_name,
            "allowed_tools": allowed_tools,
        }
    return workflow


def _load_override(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as policy_file:
        return json.load(policy_file)


def _ensure_terminal_completion_tools(data: dict[str, Any]) -> None:
    """Keep mandatory specialist terminal tools when older policies override lists."""
    default_specialists = set(DEFAULT_POLICY["agents"]) - {"Orchestrator"}
    for agent_name in default_specialists:
        agent_policy = data.get("agents", {}).get(agent_name)
        if not isinstance(agent_policy, dict):
            continue
        tools = agent_policy.setdefault("tools", [])
        if "return_to_orchestrator" not in tools:
            try:
                alias_index = tools.index("finish_agent_run")
            except ValueError:
                alias_index = len(tools)
            tools.insert(alias_index, "return_to_orchestrator")
        if "finish_agent_run" not in tools:
            tools.append("finish_agent_run")


@lru_cache(maxsize=1)
def get_policy() -> AgentToolPolicy:
    """Return the effective policy, including optional local overrides."""
    from src.ariadne.config.settings import settings

    base = copy.deepcopy(DEFAULT_POLICY)
    base["workflow"] = _workflow_defaults()
    policy_path = getattr(settings, "agent_policy_path", ".ariadne/agent_policy.json")
    data = _deep_merge(base, _load_override(policy_path))
    _ensure_terminal_completion_tools(data)
    try:
        return AgentToolPolicy.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"Invalid agent policy at {policy_path}: {e}") from e


def reset_policy_cache() -> None:
    """Clear cached policy, mainly for tests and live settings changes."""
    get_policy.cache_clear()
