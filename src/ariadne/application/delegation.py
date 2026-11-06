"""Application service for durable specialist-agent delegation."""

from __future__ import annotations

import fnmatch
import inspect
import logging
import subprocess
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.ariadne.config.settings import settings
from src.ariadne.runtime import run_manager
from src.ariadne.runtime.context import (
    DelegationContext,
    delegation_scope,
    set_active_work_item_id,
)
from src.ariadne.policies.loader import get_policy
from src.ariadne.tools.agent_run_tools import AgentRunTools
from src.ariadne.work_items.models import (
    AgentCompletion,
    AgentRunFinalization,
    AgentRunDiagnostics,
    AgentRunStatus,
    GateStatus,
    VerificationStatus,
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

        work_item, workflow = self._validate_entry(
            agent_name,
            work_item_id,
        )
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
        runtime_context = DelegationContext(
            work_item_id=str(work_item_id),
            agent_name=agent_name,
            agent_run_id=str(agent_run_id),
            entry_status=work_item.status,
        )

        try:
            with delegation_scope(runtime_context):
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
                details=(
                    "The specialist run was cancelled before a result could be accepted."
                ),
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

        if run_status == AgentRunStatus.SUCCESS:
            completion, diagnostics = self._validate_success_postconditions(
                agent_name,
                work_item,
                workflow,
                completion,
                evidence,
                diagnostics,
            )
            run_status = AgentRunStatus(completion.status.value)

        finalization = self._build_finalization(
            agent_name=agent_name,
            work_item=work_item,
            workflow=workflow,
            run_status=run_status,
            completion=completion,
            evidence=evidence,
            raw_response=raw_response,
            diagnostics=diagnostics,
            starting_commit=starting_commit,
        )
        finish_result = self.ticket_tools.finalize_agent_run(
            str(agent_run_id),
            finalization,
        )
        if str(finish_result).startswith("Error"):
            raise RuntimeError(str(finish_result))

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

    def _validate_entry(self, agent_name: str, work_item_id: str):
        store = self.ticket_tools.system
        try:
            work_item = store.get_work_item(work_item_id)
        except Exception as error:
            raise DelegationRejectedError(str(error)) from error

        workflow = get_policy().workflow.get(work_item.status)
        if not workflow:
            raise DelegationRejectedError(
                f"No workflow policy is defined for status '{work_item.status}'."
            )
        if workflow.owner != agent_name:
            raise DelegationRejectedError(
                f"Cannot delegate work item #{work_item_id} in '{work_item.status}' "
                f"to '{agent_name}'; this phase is owned by '{workflow.owner}'."
            )

        running = store.get_running_agent_run(work_item_id)
        if running:
            raise DelegationRejectedError(
                f"Work item #{work_item_id} already has RUNNING agent run "
                f"#{running.id} ({running.agent_name})."
            )

        blockers = store.get_blockers(work_item_id)
        if blockers:
            raise DelegationRejectedError(
                f"Work item #{work_item_id} is blocked by unresolved work items: "
                f"{', '.join(f'#{blocker}' for blocker in blockers)}."
            )

        missing_artifacts = [
            pattern
            for pattern in workflow.entry_required_artifact_patterns
            if not self._has_artifact(work_item.artifacts, pattern)
        ]
        if missing_artifacts:
            raise DelegationRejectedError(
                f"Work item #{work_item_id} is missing required entry artifacts: "
                f"{', '.join(missing_artifacts)}."
            )

        missing_gates = [
            gate
            for gate in workflow.entry_required_gates
            if self._gate_status(work_item, gate) != GateStatus.APPROVED
        ]
        if missing_gates:
            raise DelegationRejectedError(
                f"Work item #{work_item_id} requires approved entry gates: "
                f"{', '.join(missing_gates)}."
            )

        if workflow.requires_clean_worktree:
            clean_check = self._check_clean_git_status()
            if clean_check:
                raise DelegationRejectedError(clean_check)

        return work_item, workflow

    def _validate_success_postconditions(
        self,
        agent_name: str,
        work_item: Any,
        workflow: Any,
        completion: AgentCompletion,
        evidence: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> tuple[AgentCompletion, dict[str, Any]]:
        errors = []
        artifacts = [*work_item.artifacts, *completion.artifacts]
        if workflow.required_artifact_pattern and not self._has_artifact(
            artifacts, workflow.required_artifact_pattern
        ):
            errors.append(
                "Missing required output artifact matching "
                f"{workflow.required_artifact_pattern}."
            )

        if workflow.gate_to_update:
            gate_decision = completion.gate_decision
            if (
                not gate_decision
                or gate_decision.gate.lower() != workflow.gate_to_update.lower()
                or gate_decision.decision != GateStatus.APPROVED
            ):
                errors.append(
                    f"Completion must approve the '{workflow.gate_to_update}' gate."
                )

        failed_verification = [
            result.name
            for result in completion.verification
            if result.status == VerificationStatus.FAILED
        ]
        if failed_verification:
            errors.append(
                "Verification failed: " + ", ".join(failed_verification) + "."
            )
        if workflow.requires_verification and not completion.verification:
            errors.append("At least one verification result is required.")

        if workflow.requires_clean_worktree and evidence.get("status_short"):
            errors.append("The final Git worktree is not clean.")

        if not errors:
            return completion, diagnostics

        failed_payload = completion.model_dump(mode="json", exclude_none=True)
        failed_payload.update(
            {
                "status": "FAILED",
                "summary": f"{agent_name} success postconditions were not satisfied.",
                "details": "\n".join(errors),
                "blockers": errors,
            }
        )
        failed_completion = AgentCompletion.model_validate(failed_payload)
        postcondition_diagnostics = dict(diagnostics)
        postcondition_diagnostics.update(
            AgentRunDiagnostics(
                failure_kind="postcondition_failure",
                error_type="CompletionPostconditionError",
                error_message=" ".join(errors),
            ).model_dump(mode="json")
        )
        return failed_completion, postcondition_diagnostics

    def _build_finalization(
        self,
        *,
        agent_name: str,
        work_item: Any,
        workflow: Any,
        run_status: AgentRunStatus,
        completion: AgentCompletion,
        evidence: dict[str, Any],
        raw_response: str,
        diagnostics: dict[str, Any],
        starting_commit: str,
    ) -> AgentRunFinalization:
        completion_payload = completion.model_dump(mode="json", exclude_none=True)
        handoff_context = self._format_handoff_context(
            agent_name,
            completion_payload,
            evidence,
            run_status=run_status,
        )
        handoff_metadata = self._handoff_context_metadata(
            completion_payload,
            evidence,
            run_status=run_status,
        )
        latest_commit = str(evidence.get("latest_commit") or "")
        commit_hashes = []
        if latest_commit and latest_commit != starting_commit:
            commit_hashes.append(latest_commit)

        next_status = workflow.next_state or ""
        if run_status == AgentRunStatus.FAILED:
            exit_status = "Blocked"
        elif run_status == AgentRunStatus.CANCELLED:
            exit_status = work_item.status
            next_status = ""
        else:
            exit_status = next_status

        return AgentRunFinalization(
            run_status=run_status,
            completion=completion,
            evidence=evidence,
            exit_status=exit_status,
            raw_response=raw_response,
            diagnostics=diagnostics,
            next_status=next_status,
            resumable_status=work_item.status,
            blocked_reason=self._blocked_reason(completion)
            if run_status == AgentRunStatus.FAILED
            else "",
            commit_hashes=commit_hashes,
            handoff_context=handoff_context,
            handoff_metadata=handoff_metadata,
            comment=self._failure_comment(completion)
            if run_status == AgentRunStatus.FAILED
            else "",
        )

    def _has_artifact(self, artifacts: list[Any], pattern: str) -> bool:
        return any(
            fnmatch.fnmatch(str(getattr(artifact, "url", "")), pattern)
            for artifact in artifacts
        )

    def _gate_status(self, work_item: Any, gate: str) -> GateStatus:
        value = getattr(work_item, f"gate_{gate.lower()}_status", GateStatus.PENDING)
        return value if isinstance(value, GateStatus) else GateStatus(value)

    def _blocked_reason(self, completion: AgentCompletion) -> str:
        values = [completion.summary, *completion.blockers]
        return " | ".join(value for value in values if value).strip()

    def _failure_comment(self, completion: AgentCompletion) -> str:
        lines = ["Delegated agent failed.", f"Summary: {completion.summary}"]
        if completion.details:
            lines.extend(["", "Details:", completion.details])
        if completion.blockers:
            lines.extend(["", "Blockers:"])
            lines.extend(f"- {blocker}" for blocker in completion.blockers)
        return "\n".join(lines)

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
