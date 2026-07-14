import json
from typing import Any

from pydantic import ValidationError

from src.ariadne.work_items.models import (
    AgentCompletion,
    AgentCompletionStatus,
    CompletionArtifact,
)


class AgentRunTools:
    """
    Tools for standardizing delegated agent completion results.
    """

    def finish_agent_run(
        self,
        status: str,
        summary: str,
        details: str = "",
        decisions: list[str] | None = None,
        blockers: list[str] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        verification: list[dict[str, Any]] | None = None,
        gate_decision: dict[str, Any] | None = None,
    ) -> str:
        """
        Finish this delegated agent run with a compact structured handoff.
        """
        normalized_status = status.strip().upper()
        try:
            completion_status = AgentCompletionStatus(normalized_status)
        except ValueError:
            return "Error: status must be SUCCESS or FAILED."

        normalized_summary = summary.strip()
        if not normalized_summary:
            return "Error: summary cannot be empty."

        try:
            completion = AgentCompletion(
                status=completion_status,
                summary=normalized_summary,
                details=details,
                decisions=_string_list(decisions),
                blockers=_string_list(blockers),
                artifacts=_artifact_list(artifacts),
                verification=verification or [],
                gate_decision=gate_decision,
            )
        except ValidationError as e:
            return f"Error: invalid completion payload: {e.errors(include_url=False)}"

        payload = completion.model_dump(mode="json", exclude_none=True)
        return "[AGENT_RUN_COMPLETE]\n" + json.dumps(payload, indent=2, sort_keys=True)


def _string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _artifact_list(values: list[dict[str, Any]] | None) -> list[CompletionArtifact]:
    if not values:
        return []
    artifacts = []
    for value in values:
        if not isinstance(value, dict):
            continue
        url = str(value.get("url") or value.get("path") or value.get("file") or "").strip()
        if not url:
            continue
        metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
        metadata = dict(metadata)
        for key, item in value.items():
            if key not in {"title", "name", "url", "path", "file", "type", "stable_id", "metadata"}:
                metadata[key] = item
        artifacts.append(
            CompletionArtifact(
                title=str(value.get("title") or value.get("name") or url),
                url=url,
                type=str(value.get("type") or "link"),
                stable_id=str(value.get("stable_id") or ""),
                metadata=metadata,
            )
        )
    return artifacts
