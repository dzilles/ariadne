"""Application service for durable specialist-agent delegation."""

from __future__ import annotations

import inspect
import logging
import subprocess
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.ariadne.config.settings import settings
from src.ariadne.runtime import run_manager
from src.ariadne.runtime.context import set_active_work_item_id
from src.ariadne.tools.agent_run_tools import AgentRunTools
from src.ariadne.work_items.models import (
    AgentCompletion,
    AgentRunDiagnostics,
    AgentRunStatus,
    WorkItemStatus,
)

logger = logging.getLogger(__name__)

MAX_RAW_AGENT_RESPONSE_CHARS = 20_000
SPECIALIST_AGENT_NAMES = (
    "Requirements",
    "QM",
    "Architect",
    "Developer",
    "Tester",
    "QA",
)

_ENTRY_STATUS_BY_AGENT = {
    "Requirements": WorkItemStatus.READY_FOR_ANALYSIS,
    "QM": WorkItemStatus.READY_FOR_REVIEW,
    "Architect": WorkItemStatus.READY_FOR_DESIGN,
    "Developer": WorkItemStatus.READY_FOR_DEVELOPMENT,
    "Tester": WorkItemStatus.READY_FOR_TESTING,
    "QA": WorkItemStatus.READY_FOR_QA,
}


class DelegationRejectedError(RuntimeError):
    """Raised when delegation cannot start."""


@dataclass(frozen=True)
class DelegationResult:
    """Typed outcome returned by the delegation service to the Orchestrator."""

    work_item_id: str
    agent_name: str
    agent_run_id: str
    run_status: AgentRunStatus
    completion: AgentCompletion
    evidence: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    raw_response: str = ""
    execution_error: str = ""

    def to_orchestrator_message(self) -> str:
        """Render the typed result for the Orchestrator's tool response."""
        if self.execution_error:
            return f"Error delegating to {self.agent_name}: {self.execution_error}"

        if self.diagnostics.get("failure_kind") == "invalid_completion":
            return (
                f"[{self.agent_name} Handoff Failure]:\n"
                f"{self.completion.summary}\n{self.completion.details}"
            )

        lines = [
            f"[{self.agent_name} Completion: {self.run_status.value}]",
            f"Agent run: {self.agent_run_id}",
            f"Summary: {self.completion.summary}",
        ]
        if self.completion.details:
            lines.extend(["", "Details:", self.completion.details])
        if self.completion.blockers:
            lines.extend(["", "Blockers:"])
            lines.extend(f"- {blocker}" for blocker in self.completion.blockers)
        return "\n".join(lines)


class DelegationService:
    """Coordinate one specialist run from durable start through finalization."""

    def __init__(
        self,
        ticket_tools: Any,
        *,
        agent_factories: Mapping[str, Callable[..., Any]] | None = None,
        project_path: str | None = None,
    ) -> None:
        self.ticket_tools = ticket_tools
        self._agent_factories = agent_factories
        self.project_path = project_path or settings.project_path

    def delegate(
        self,
        agent_name: str,
        work_item_id: str,
        task_description: str,
    ) -> DelegationResult:
        """Run a specialist and return its typed, durably finalized outcome."""
        agent_factories = self._get_agent_factories()
        if agent_name == "Orchestrator" or agent_name not in agent_factories:
            available = [name for name in agent_factories if name != "Orchestrator"]
            raise DelegationRejectedError(
                f"Unknown specialist agent '{agent_name}'. Available: {available}"
            )

        clean_check = self._check_clean_git_status()
        if clean_check:
            raise DelegationRejectedError(clean_check)

        set_active_work_item_id(work_item_id)
        agent_run_id = self.ticket_tools.start_agent_run(
            work_item_id,
            agent_name,
            task_description,
        )
        if str(agent_run_id).startswith("Error"):
            raise DelegationRejectedError(str(agent_run_id))

        starting_commit = self._git_output(["rev-parse", "--short", "HEAD"])
        response = ""
        diagnostics: dict[str, Any] = {}
        execution_error = ""
        completion_tools = AgentRunTools()

        try:
            self._prepare_work_item_for_agent(work_item_id, agent_name)
            agent = self._create_specialist(
                agent_factories[agent_name],
                completion_tools,
            )
            response = str(
                agent.chat(
                    self._build_delegation_prompt(
                        agent_name,
                        work_item_id,
                        task_description,
                    )
                )
                or ""
            )
            completion, diagnostics = self._resolve_completion(
                agent_name,
                completion_tools,
            )
        except Exception as error:
            execution_error = str(error)
            completion = self._exception_completion(agent_name, error)
            diagnostics = AgentRunDiagnostics(
                failure_kind="exception",
                error_type=type(error).__name__,
                error_message=str(error),
                traceback=traceback.format_exc(),
            ).model_dump(mode="json")

        run_status = AgentRunStatus(completion.status.value)
        if run_manager.is_cancel_requested():
            run_status = AgentRunStatus.CANCELLED
            completion = AgentCompletion(
                status="FAILED",
                summary=f"Delegation to {agent_name} was cancelled.",
                details="The specialist run was cancelled before a result could be accepted.",
                blockers=["Review partial work and Git evidence before retrying."],
            )
            diagnostics = AgentRunDiagnostics(
                failure_kind="cancelled",
                error_type="RunCancelledError",
                error_message="Run cancellation requested by user.",
            ).model_dump(mode="json")

        evidence = self._collect_handoff_evidence()
        evidence["starting_commit"] = starting_commit
        raw_response, was_truncated = self._truncate_raw_response(response)
        if was_truncated:
            diagnostics = dict(diagnostics)
            diagnostics["raw_response_truncated"] = True

        self._finalize_agent_outcome(
            work_item_id=work_item_id,
            agent_name=agent_name,
            agent_run_id=str(agent_run_id),
            run_status=run_status,
            raw_response=raw_response,
            completion=completion,
            evidence=evidence,
            diagnostics=diagnostics,
        )
        return DelegationResult(
            work_item_id=work_item_id,
            agent_name=agent_name,
            agent_run_id=str(agent_run_id),
            run_status=run_status,
            completion=completion,
            evidence=evidence,
            diagnostics=diagnostics,
            raw_response=raw_response,
            execution_error=execution_error,
        )

    def _get_agent_factories(self) -> Mapping[str, Callable[..., Any]]:
        if self._agent_factories is None:
            from src.ariadne.application.agents import AGENT_CLASSES

            self._agent_factories = AGENT_CLASSES
        return self._agent_factories

    def _create_specialist(
        self,
        factory: Callable[..., Any],
        completion_tools: AgentRunTools,
    ) -> Any:
        try:
            parameters = inspect.signature(factory).parameters.values()
        except (TypeError, ValueError):
            parameters = ()
        supports_completion_tools = any(
            parameter.name == "agent_run_tools"
            or parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        if supports_completion_tools:
            agent = factory(agent_run_tools=completion_tools)
        else:
            agent = factory()
        setattr(agent, "_propagate_delegation_errors", True)
        return agent

    def _prepare_work_item_for_agent(self, work_item_id: str, agent_name: str) -> None:
        target_status = _ENTRY_STATUS_BY_AGENT.get(agent_name)
        if not target_status:
            return
        logger.info(
            "Delegation service: ensuring work item #%s is in status '%s' for %s.",
            work_item_id,
            target_status.value,
            agent_name,
        )
        self.ticket_tools.update_status(work_item_id, target_status.value)
        self.ticket_tools.post_comment(
            work_item_id,
            (
                f"Ariadne Orchestrator: Delegating task to {agent_name} agent. "
                f"Moving work item to {target_status.value}."
            ),
        )

    def _build_delegation_prompt(
        self,
        agent_name: str,
        work_item_id: str,
        task_description: str,
    ) -> str:
        context_bundle = self.ticket_tools.get_context_bundle(
            work_item_id,
            target_agent=agent_name,
        )
        return f"""Context: You are working on work item #{work_item_id}.

Context bundle:
{context_bundle}

Task:
{task_description}

Before you finish, you MUST:
1. Check the current work item with `get_work_item` so your answer reflects the latest status, artifacts, and comments.
2. Complete the delegated task as far as your role allows.
3. Finish by calling `return_to_orchestrator` exactly once with status, summary, and any relevant details, decisions, blockers, intentional artifacts, verification, and gate decision.

Do not call `append_shared_context`. Only the Orchestrator writes shared context after reviewing your completion.
Do not choose the next agent. The Orchestrator decides workflow routing.
"""

    def _resolve_completion(
        self,
        agent_name: str,
        completion_tools: AgentRunTools,
    ) -> tuple[AgentCompletion, dict[str, Any]]:
        if completion_tools.terminal_call_count == 1 and completion_tools.completion:
            return completion_tools.completion, {}

        if completion_tools.terminal_call_count > 1:
            error = "The specialist called its terminal completion tool more than once."
        else:
            error = "The specialist did not call return_to_orchestrator exactly once."
        failed_completion = AgentCompletion(
            status="FAILED",
            summary=f"{agent_name} returned an invalid completion handoff.",
            details=error,
            blockers=[
                "A valid terminal completion is required before the workflow can continue."
            ],
        )
        diagnostics = AgentRunDiagnostics(
            failure_kind="invalid_completion",
            error_type="CompletionValidationError",
            error_message=error,
        )
        return failed_completion, diagnostics.model_dump(mode="json")

    def _exception_completion(
        self, agent_name: str, error: Exception
    ) -> AgentCompletion:
        return AgentCompletion(
            status="FAILED",
            summary=f"Error delegating to {agent_name}: {error}",
            details=(
                "The delegated agent did not complete because its execution raised "
                "an exception."
            ),
            blockers=["Review the agent-run diagnostics before retrying this phase."],
        )

    def _finalize_agent_outcome(
        self,
        *,
        work_item_id: str,
        agent_name: str,
        agent_run_id: str,
        run_status: AgentRunStatus,
        raw_response: str,
        completion: AgentCompletion,
        evidence: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> None:
        completion_payload = completion.model_dump(mode="json", exclude_none=True)
        finish_result = self.ticket_tools.finish_agent_run(
            agent_run_id,
            run_status.value,
            completion_payload,
            evidence,
            exit_status="Blocked" if run_status == AgentRunStatus.FAILED else "",
            raw_response=raw_response,
            diagnostics=diagnostics,
        )
        if str(finish_result).startswith("Error"):
            raise RuntimeError(str(finish_result))

        if run_status != AgentRunStatus.CANCELLED:
            self._apply_agent_run_to_work_item(
                work_item_id,
                completion,
                evidence,
                agent_run_id=agent_run_id,
            )
        self._append_agent_handoff_context(
            work_item_id,
            agent_name,
            completion,
            evidence,
            agent_run_id=agent_run_id,
            run_status=run_status,
        )

    def _apply_agent_run_to_work_item(
        self,
        work_item_id: str,
        completion: AgentCompletion,
        evidence: dict[str, Any],
        *,
        agent_run_id: str,
    ) -> None:
        if completion.status.value == AgentRunStatus.FAILED.value:
            self._apply_failed_agent_run_to_work_item(work_item_id, completion)
            return

        starting_commit = evidence.get("starting_commit") or ""
        latest_commit = evidence.get("latest_commit") or ""
        if latest_commit and latest_commit != starting_commit:
            result = self.ticket_tools.add_commit_hash(work_item_id, latest_commit)
            logger.info(
                "Commit hash update result for work item #%s: %s", work_item_id, result
            )

        for artifact in completion.artifacts:
            metadata = dict(artifact.metadata)
            if artifact.stable_id:
                metadata["stable_id"] = artifact.stable_id
            result = self.ticket_tools.add_link(
                work_item_id,
                artifact.title,
                artifact.url,
                artifact_type=artifact.type,
                agent_run_id=agent_run_id,
                metadata=metadata,
            )
            logger.info(
                "Artifact link update result for work item #%s: %s",
                work_item_id,
                result,
            )

    def _apply_failed_agent_run_to_work_item(
        self,
        work_item_id: str,
        completion: AgentCompletion,
    ) -> None:
        status_result = self.ticket_tools.update_status(work_item_id, "Blocked")
        logger.info(
            "Failure status update result for work item #%s: %s",
            work_item_id,
            status_result,
        )

        lines = ["Delegated agent failed.", f"Summary: {completion.summary}"]
        if completion.details:
            lines.extend(["", "Details:", completion.details])
        if completion.blockers:
            lines.extend(["", "Blockers:"])
            lines.extend(f"- {blocker}" for blocker in completion.blockers)

        comment_result = self.ticket_tools.post_comment(work_item_id, "\n".join(lines))
        logger.info(
            "Failure comment result for work item #%s: %s", work_item_id, comment_result
        )

    def _append_agent_handoff_context(
        self,
        work_item_id: str,
        agent_name: str,
        completion: AgentCompletion,
        evidence: dict[str, Any],
        *,
        agent_run_id: str,
        run_status: AgentRunStatus,
    ) -> None:
        completion_payload = completion.model_dump(mode="json", exclude_none=True)
        context = self._format_handoff_context(
            agent_name,
            completion_payload,
            evidence,
            run_status=run_status,
        )
        metadata = self._handoff_context_metadata(
            completion_payload,
            evidence,
            run_status=run_status,
        )
        result = self.ticket_tools.append_shared_context(
            work_item_id,
            agent_name,
            context,
            agent_run_id=agent_run_id,
            metadata=metadata,
        )
        logger.info(
            "Shared context append result for work item #%s: %s", work_item_id, result
        )

    def _format_handoff_context(
        self,
        agent_name: str,
        completion: dict[str, Any],
        evidence: dict[str, Any],
        *,
        run_status: AgentRunStatus | None = None,
    ) -> str:
        status = run_status.value if run_status else completion.get("status", "UNKNOWN")
        lines = [
            f"Delegated agent: {agent_name}",
            f"Status: {status}",
            f"Summary: {completion.get('summary', '')}",
        ]
        if completion.get("details"):
            lines.extend(["", "Details:", str(completion["details"])])
        for label, key in (
            ("Decisions", "decisions"),
            ("Blockers", "blockers"),
            ("Artifacts", "artifacts"),
        ):
            values = completion.get(key) or []
            if values:
                lines.extend(["", f"{label}:"])
                lines.extend(f"- {value}" for value in values)

        lines.extend(
            [
                "",
                "Automatic evidence:",
                f"- Branch: {evidence.get('branch') or 'Unknown'}",
                f"- Latest commit: {evidence.get('latest_commit') or 'Unknown'}",
                f"- Git status: {evidence.get('status_short') or 'Clean'}",
                (
                    "- Changed files: "
                    f"{', '.join(evidence.get('changed_files') or []) or 'None'}"
                ),
                f"- Diff stat: {evidence.get('diff_stat') or 'No diff'}",
            ]
        )
        return "\n".join(lines)

    def _handoff_context_metadata(
        self,
        completion: dict[str, Any],
        evidence: dict[str, Any],
        *,
        run_status: AgentRunStatus | None = None,
    ) -> dict[str, Any]:
        metadata = {
            "status": (
                run_status.value if run_status else completion.get("status", "UNKNOWN")
            ),
            "latest_commit": evidence.get("latest_commit") or "",
            "changed_files": evidence.get("changed_files") or [],
        }
        if completion.get("artifacts"):
            metadata["artifact_count"] = len(completion.get("artifacts") or [])
        return metadata

    def _check_clean_git_status(self) -> str:
        result = self._run_git(["status", "--porcelain"])
        if result["returncode"] != 0:
            return f"Error checking git status before delegation: {result['stderr']}"
        status = result["stdout"].strip()
        if status:
            return (
                "BLOCK: Cannot delegate to another agent while the git worktree is dirty.\n"
                "Commit, stash, or revert the current changes first.\n\n"
                f"Git status:\n{status}"
            )
        return ""

    def _collect_handoff_evidence(self) -> dict[str, Any]:
        return {
            "branch": self._git_output(["branch", "--show-current"]) or "Detached HEAD",
            "status_short": self._git_output(["status", "--short"]),
            "diff_stat": self._git_output(["diff", "--stat"]),
            "changed_files": self._git_output(["diff", "--name-only"]).splitlines(),
            "latest_commit": self._git_output(["rev-parse", "--short", "HEAD"]),
        }

    def _run_git(self, args: list[str]) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except Exception as error:
            return {"returncode": 1, "stdout": "", "stderr": str(error)}
        return {
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    def _git_output(self, args: list[str]) -> str:
        result = self._run_git(args)
        return result["stdout"] if result["returncode"] == 0 else ""

    def _truncate_raw_response(self, response: str) -> tuple[str, bool]:
        value = str(response or "")
        if len(value) <= MAX_RAW_AGENT_RESPONSE_CHARS:
            return value, False
        return value[:MAX_RAW_AGENT_RESPONSE_CHARS], True


class CoordinatedSpecialistAgent:
    """Sync chat adapter that routes a manually selected specialist via Orchestrator."""

    def __init__(
        self, orchestrator: Any, specialist_name: str, work_item_id: str
    ) -> None:
        self.orchestrator = orchestrator
        self.specialist_name = specialist_name
        self.work_item_id = work_item_id

    def chat(self, message: str) -> str:
        """Delegate the user's message instead of running the specialist directly."""
        return self.orchestrator.delegate_to_agent(
            self.specialist_name,
            self.work_item_id,
            message,
        )
