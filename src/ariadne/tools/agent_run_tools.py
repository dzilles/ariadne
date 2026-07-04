import json
from typing import Any


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
    ) -> str:
        """
        Finish this delegated agent run with a compact structured handoff.
        """
        normalized_status = status.strip().upper()
        if normalized_status not in {"SUCCESS", "FAILED"}:
            return "Error: status must be SUCCESS or FAILED."

        normalized_summary = summary.strip()
        if not normalized_summary:
            return "Error: summary cannot be empty."

        payload = {
            "status": normalized_status,
            "summary": normalized_summary,
            "details": details.strip(),
            "decisions": _string_list(decisions),
            "blockers": _string_list(blockers),
            "artifacts": _artifact_list(artifacts),
        }
        return "[AGENT_RUN_COMPLETE]\n" + json.dumps(payload, indent=2, sort_keys=True)


def _string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _artifact_list(values: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    if not values:
        return []
    artifacts = []
    for value in values:
        if not isinstance(value, dict):
            continue
        artifact = {
            "title": str(value.get("title", "")).strip(),
            "url": str(value.get("url", "")).strip(),
            "type": str(value.get("type", "")).strip(),
        }
        if artifact["title"] or artifact["url"]:
            artifacts.append(artifact)
    return artifacts
