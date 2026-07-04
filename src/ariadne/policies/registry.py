"""Resolve policy tool names to Python callables."""

from __future__ import annotations

from collections.abc import Callable
import inspect
from typing import Any

from .loader import get_policy


def get_agent_tool_names(agent_name: str) -> list[str]:
    """Return configured tool names for an agent."""
    agent = get_policy().agents.get(agent_name)
    if not agent:
        raise KeyError(f"Agent '{agent_name}' is not defined in policy.")
    return list(agent.tools)


def build_agent_tools(
    agent_name: str,
    tool_sources: list[Any],
    *,
    extra_tools: dict[str, Callable] | None = None,
) -> list[Callable]:
    """Resolve an agent's configured tool names from source objects."""
    tools = []
    extra_tools = extra_tools or {}
    for tool_name in get_agent_tool_names(agent_name):
        if tool_name in extra_tools:
            tools.append(extra_tools[tool_name])
            continue

        for source in tool_sources:
            if source is not None and hasattr(source, tool_name):
                tools.append(getattr(source, tool_name))
                break
        else:
            raise ValueError(
                f"Tool '{tool_name}' for agent '{agent_name}' has no registered callable."
            )
    return tools


def build_tool_docs(tools: list[Callable]) -> str:
    """Format prompt documentation from the exact tools given to the agent."""
    lines = []
    for tool in tools:
        name = getattr(tool, "__name__", tool.__class__.__name__)
        signature = _format_signature(tool)
        description = _format_description(tool)
        lines.append(f"* `{name}{signature}`: {description}")
    return "\n".join(lines)


def _format_signature(tool: Callable) -> str:
    try:
        signature = inspect.signature(tool)
    except (TypeError, ValueError):
        return "()"

    parameters = []
    for parameter in signature.parameters.values():
        if parameter.name == "self":
            continue
        parameters.append(parameter.name)
    return f"({', '.join(parameters)})"


def _format_description(tool: Callable) -> str:
    doc = inspect.getdoc(tool) or "No description provided."
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "No description provided."
