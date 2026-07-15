import json
import threading
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

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._completion: AgentCompletion | None = None
        self._terminal_call_count = 0

    @property
    def completion(self) -> AgentCompletion | None:
        """Return the typed completion recorded for this delegated run."""
        with self._lock:
            return self._completion

    @property
    def terminal_call_count(self) -> int:
        """Return how many valid terminal completion calls were attempted."""
        with self._lock:
            return self._terminal_call_count

    def return_to_orchestrator(
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
        """Return one typed semantic completion to the Orchestrator."""
        completion_or_error = self._build_completion(
            status=status,
            summary=summary,
            details=details,
            decisions=decisions,
            blockers=blockers,
            artifacts=artifacts,
            verification=verification,
            gate_decision=gate_decision,
        )
        if isinstance(completion_or_error, str):
            return completion_or_error

        with self._lock:
            self._terminal_call_count += 1
            if self._completion is not None:
                return "Error: return_to_orchestrator may only be called once per agent run."
            self._completion = completion_or_error

        return _serialize_completion(completion_or_error)

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
        Compatibility alias for return_to_orchestrator.
        """
        return self.return_to_orchestrator(
            status=status,
            summary=summary,
            details=details,
            decisions=decisions,
            blockers=blockers,
            artifacts=artifacts,
            verification=verification,
            gate_decision=gate_decision,
        )

    def _build_completion(
        self,
        *,
        status: str,
        summary: str,
        details: str,
        decisions: list[str] | None,
        blockers: list[str] | None,
        artifacts: list[dict[str, Any]] | None,
        verification: list[dict[str, Any]] | None,
        gate_decision: dict[str, Any] | None,
    ) -> AgentCompletion | str:
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

        return completion


def _serialize_completion(completion: AgentCompletion) -> str:
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
        url = str(
            value.get("url") or value.get("path") or value.get("file") or ""
        ).strip()
        if not url:
            continue
        metadata = (
            value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
        )
        metadata = dict(metadata)
        for key, item in value.items():
            if key not in {
                "title",
                "name",
                "url",
                "path",
                "file",
                "type",
                "stable_id",
                "metadata",
            }:
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
