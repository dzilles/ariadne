import logging
import json
import os
import subprocess
import traceback

from pydantic import ValidationError

from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.policies.registry import build_agent_tools, build_tool_docs
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.config.settings import settings
from src.ariadne.infrastructure.container import DependencyRegistry
from src.ariadne.work_items.models import AgentCompletion, AgentRunDiagnostics

logger = logging.getLogger(__name__)

MAX_RAW_AGENT_RESPONSE_CHARS = 20_000

class OrchestratorAgent(BaseAgent):
    """
    Orchestrator Agent responsible for coordinating the workflow and high-level planning.
    """

    def __init__(self, ticket_tools=None, file_tools=None):
        super().__init__()

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_work_item_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # Map to expected tool names
        self.get_ticket_details = self.ticket_tools.get_work_item
        self.update_work_item = self.ticket_tools.update_status
        self.add_comment = self.ticket_tools.post_comment

        raw_tools = build_agent_tools(
            "Orchestrator",
            [self.ticket_tools, self.file_tools],
            extra_tools={
                "search_codebase": self.search_codebase,
                "git_diff": self.git_diff,
                "delete_agent_context": self.delete_agent_context,
                "delegate_to_agent": self.delegate_to_agent,
            },
        )
        self.tools = wrap_tools_with_error_handling(raw_tools)

        self.tool_docs = build_tool_docs(raw_tools)

        self._init_executor(self.tools, self._get_system_message())

    def search_codebase(
        self,
        query: str,
        directory: str = ".",
        file_glob: str = "*",
        max_results: int = 50,
    ) -> str:
        """
        Search the codebase for text using ripgrep-style grep output.
        """
        query = query.strip()
        if not query:
            return "Error: query cannot be empty."
        try:
            max_results = max(1, int(max_results))
        except (TypeError, ValueError):
            return "Error: max_results must be a positive integer."

        try:
            search_root = self._resolve_project_path(directory)
            result = subprocess.run(
                [
                    "rg",
                    "--line-number",
                    "--with-filename",
                    "--glob",
                    file_glob,
                    query,
                    search_root,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError:
            return self._search_codebase_without_rg(query, directory, file_glob, max_results)
        except Exception as e:
            return f"Error searching codebase: {e}"

        if result.returncode == 1:
            return "No matches found."
        if result.returncode != 0:
            return f"Error searching codebase: {result.stderr.strip()}"

        lines = result.stdout.splitlines()
        truncated = len(lines) > max_results
        lines = lines[:max_results]
        output = "\n".join(self._format_search_line(line) for line in lines)
        if truncated:
            output += f"\n... truncated after {max_results} matches"
        return output

    def git_diff(self, staged: bool = False, file_path: str | None = None) -> str:
        """
        Show the current git diff for unstaged changes, staged changes, or one file.
        """
        command = ["git", "diff"]
        if staged:
            command.append("--cached")
        if file_path:
            command.extend(["--", file_path])

        try:
            result = subprocess.run(
                command,
                cwd=settings.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except Exception as e:
            return f"Error running git diff: {e}"

        if result.returncode != 0:
            return f"Error running git diff: {result.stderr.strip()}"
        return result.stdout or "No diff."

    def delete_agent_context(self, agent_name: str) -> str:
        """
        Delete the saved prompt and chat context for an agent.
        """
        try:
            from src.ariadne.application.history import clear_history

            if clear_history(agent_name):
                return f"Success: Deleted saved context for {agent_name}"
            return f"Error: Failed to delete saved context for {agent_name}"
        except Exception as e:
            return f"Error deleting agent context: {e}"

    def _resolve_project_path(self, path: str) -> str:
        project_root = os.path.abspath(settings.project_path)
        candidate = path if os.path.isabs(path) else os.path.join(project_root, path)
        candidate = os.path.abspath(candidate)
        if os.path.commonpath([project_root, candidate]) != project_root:
            raise ValueError("Path must stay inside the project root.")
        return candidate

    def _format_search_line(self, line: str) -> str:
        project_root = os.path.abspath(settings.project_path)
        parts = line.split(":", 2)
        if len(parts) < 3:
            return line
        file_path, line_number, match = parts
        try:
            file_path = os.path.relpath(file_path, project_root)
        except ValueError:
            pass
        return f"{file_path}:{line_number}:{match}"

    def _search_codebase_without_rg(
        self,
        query: str,
        directory: str,
        file_glob: str,
        max_results: int,
    ) -> str:
        import fnmatch

        matches = []
        search_root = self._resolve_project_path(directory)
        project_root = os.path.abspath(settings.project_path)
        for root, _, files in os.walk(search_root):
            for file_name in files:
                if not fnmatch.fnmatch(file_name, file_glob):
                    continue
                path = os.path.join(root, file_name)
                try:
                    with open(path, "r", encoding="utf-8") as candidate:
                        for line_number, line in enumerate(candidate, start=1):
                            if query in line:
                                rel_path = os.path.relpath(path, project_root)
                                matches.append(f"{rel_path}:{line_number}:{line.rstrip()}")
                                if len(matches) >= max_results:
                                    return "\n".join(matches) + f"\n... truncated after {max_results} matches"
                except UnicodeDecodeError:
                    continue
                except OSError:
                    continue
        return "\n".join(matches) if matches else "No matches found."

    def delegate_to_agent(self, agent_name: str, work_item_id: str, task_description: str) -> str:
        """
        Delegates a task to a specialized agent and automatically updates the work item status.
        The Orchestrator MUST use this to move through the V-Model.
        
        Args:
            agent_name: Name of the agent (Requirements, Architect, Developer, Tester, QA)
            work_item_id: The ID of the work item.
            task_description: Specific instructions for the agent.
        """
        from src.ariadne.application.agents import AGENT_CLASSES
        from src.ariadne.runtime.context import set_active_work_item_id
        from src.ariadne.work_items.models import WorkItemStatus
        
        if agent_name not in AGENT_CLASSES:
            return f"Error: Unknown agent '{agent_name}'. Available: {list(AGENT_CLASSES.keys())}"

        clean_check = self._check_clean_git_status()
        if clean_check:
            return clean_check

        # Status mapping for automatic work item reopening/progression
        status_map = {
            "Requirements": WorkItemStatus.READY_FOR_ANALYSIS,
            "Architect": WorkItemStatus.READY_FOR_DESIGN,
            "Developer": WorkItemStatus.READY_FOR_DEVELOPMENT,
            "Tester": WorkItemStatus.READY_FOR_TESTING,
            "QA": WorkItemStatus.READY_FOR_QA
        }

        # Set the context for the JIT guard
        set_active_work_item_id(work_item_id)
        agent_run_id = None
        starting_commit = ""
        response = ""
        completion = None
        diagnostics = {}
        execution_error = None
        
        try:
            agent_run_id = self.ticket_tools.start_agent_run(
                work_item_id,
                agent_name,
                task_description,
            )
            if str(agent_run_id).startswith("Error"):
                return str(agent_run_id)
            starting_commit = self._git_output(["rev-parse", "--short", "HEAD"])

            # 1. Ensure work item is in the correct status for the agent
            if agent_name in status_map:
                target_status = status_map[agent_name]
                logger.info(f"Orchestrator: Ensuring work item #{work_item_id} is in status '{target_status.value}' for {agent_name} agent.")
                # We update it to ensure it's not 'Done' or in a previous state
                self.update_work_item(work_item_id=work_item_id, status=target_status.value)
                self.add_comment(work_item_id=work_item_id, comment=f"Ariadne Orchestrator: Delegating task to {agent_name} agent. Moving work item to {target_status.value}.")

            # 2. Instantiate and chat with agent
            agent_instance = AGENT_CLASSES[agent_name]()
            response = agent_instance.chat(
                self._build_delegation_prompt(agent_name, work_item_id, task_description)
            )
            completion, diagnostics = self._normalize_agent_completion(agent_name, response)
        except Exception as e:
            execution_error = e
            completion = self._exception_completion(agent_name, e)
            diagnostics = AgentRunDiagnostics(
                failure_kind="exception",
                error_type=type(e).__name__,
                error_message=str(e),
                traceback=traceback.format_exc(),
            ).model_dump(mode="json")

        if not agent_run_id:
            return f"Error delegating to {agent_name}: agent run was not started."

        evidence = self._collect_handoff_evidence()
        evidence["starting_commit"] = starting_commit
        try:
            self._finalize_agent_outcome(
                work_item_id=work_item_id,
                agent_name=agent_name,
                agent_run_id=agent_run_id,
                response=response,
                completion=completion,
                evidence=evidence,
                diagnostics=diagnostics,
            )
        except Exception as finalization_error:
            logger.exception("Failed to finalize delegated agent run #%s", agent_run_id)
            return (
                f"Error finalizing delegation to {agent_name}: {finalization_error}. "
                f"Agent run: {agent_run_id}"
            )

        if execution_error:
            return f"Error delegating to {agent_name}: {execution_error}"
        if diagnostics.get("failure_kind") == "invalid_completion":
            return (
                f"[{agent_name} Handoff Failure]:\n"
                f"{completion['summary']}\n{completion.get('details', '')}"
            )
        return f"[{agent_name} Response]:\n{response}"

    def _finalize_agent_outcome(
        self,
        work_item_id: str,
        agent_name: str,
        agent_run_id: str,
        response: str,
        completion: dict,
        evidence: dict,
        diagnostics: dict,
    ) -> None:
        raw_response, was_truncated = self._truncate_raw_response(response)
        diagnostics = dict(diagnostics or {})
        if was_truncated:
            diagnostics["raw_response_truncated"] = True

        completion_status = completion["status"]
        finish_result = self.ticket_tools.finish_agent_run(
            agent_run_id,
            completion_status,
            completion,
            evidence,
            exit_status="Blocked" if completion_status == "FAILED" else "",
            raw_response=raw_response,
            diagnostics=diagnostics,
        )
        if str(finish_result).startswith("Error"):
            raise RuntimeError(str(finish_result))

        self._apply_agent_run_to_work_item(
            work_item_id,
            completion,
            evidence,
            agent_run_id=agent_run_id,
        )
        self._append_agent_handoff_context(
            work_item_id,
            agent_name,
            response,
            evidence,
            completion,
            agent_run_id=agent_run_id,
        )

    def _apply_agent_run_to_work_item(
        self,
        work_item_id: str,
        completion: dict,
        evidence: dict,
        agent_run_id: str | None = None,
    ) -> None:
        if completion.get("status") == "FAILED":
            self._apply_failed_agent_run_to_work_item(work_item_id, completion)
            return

        if completion.get("status") != "SUCCESS":
            return

        starting_commit = evidence.get("starting_commit") or ""
        latest_commit = evidence.get("latest_commit") or ""
        if latest_commit and latest_commit != starting_commit:
            result = self.ticket_tools.add_commit_hash(work_item_id, latest_commit)
            logger.info("Commit hash update result for work item #%s: %s", work_item_id, result)

        for artifact in completion.get("artifacts") or []:
            normalized = self._normalize_artifact_link(artifact)
            if not normalized:
                continue
            title, url, artifact_type, metadata = normalized
            result = self.ticket_tools.add_link(
                work_item_id,
                title,
                url,
                artifact_type=artifact_type,
                agent_run_id=agent_run_id,
                metadata=metadata,
            )
            logger.info("Artifact link update result for work item #%s: %s", work_item_id, result)

    def _apply_failed_agent_run_to_work_item(self, work_item_id: str, completion: dict) -> None:
        status_result = self.ticket_tools.update_status(work_item_id, "Blocked")
        logger.info("Failure status update result for work item #%s: %s", work_item_id, status_result)

        summary = str(completion.get("summary") or "Delegated agent reported failure.").strip()
        details = str(completion.get("details") or "").strip()
        blockers = [str(blocker).strip() for blocker in completion.get("blockers") or [] if str(blocker).strip()]

        lines = [
            "Delegated agent failed.",
            f"Summary: {summary}",
        ]
        if details:
            lines.extend(["", "Details:", details])
        if blockers:
            lines.append("")
            lines.append("Blockers:")
            lines.extend(f"- {blocker}" for blocker in blockers)

        comment_result = self.ticket_tools.post_comment(work_item_id, "\n".join(lines))
        logger.info("Failure comment result for work item #%s: %s", work_item_id, comment_result)

    def _normalize_artifact_link(self, artifact) -> tuple[str, str, str, dict] | None:
        if isinstance(artifact, str):
            value = artifact.strip()
            if not value:
                return None
            return ("Artifact", value, "link", {})
        if not isinstance(artifact, dict):
            return None

        url = str(
            artifact.get("url")
            or artifact.get("path")
            or artifact.get("file")
            or ""
        ).strip()
        if not url:
            return None
        title = str(
            artifact.get("title")
            or artifact.get("name")
            or artifact.get("type")
            or url
        ).strip()
        artifact_type = str(artifact.get("type") or "link").strip() or "link"
        metadata = dict(artifact.get("metadata") or {}) if isinstance(artifact.get("metadata"), dict) else {}
        if artifact.get("stable_id"):
            metadata["stable_id"] = artifact["stable_id"]
        metadata.update({
            key: value
            for key, value in artifact.items()
            if key not in {"title", "name", "url", "path", "file", "type", "stable_id", "metadata"}
        })
        return (title or url, url, artifact_type, metadata)

    def _build_delegation_prompt(self, agent_name: str, work_item_id: str, task_description: str) -> str:
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
3. Finish by calling `finish_agent_run` with status, summary, and any relevant details, decisions, blockers, and intentional artifacts.

Do not call `append_shared_context`. Only the Orchestrator writes shared context after reviewing your response.
Do not choose the next agent. The Orchestrator decides workflow routing.
"""

    def _check_clean_git_status(self) -> str:
        result = self._run_git(["status", "--porcelain"])
        if result["returncode"] != 0:
            return f"Error checking git status before delegation: {result['stderr']}"
        status = result["stdout"].strip()
        if status:
            return (
                "⛔ BLOCK: Cannot delegate to another agent while the git worktree is dirty.\n"
                "Commit, stash, or revert the current changes first.\n\n"
                f"Git status:\n{status}"
            )
        return ""

    def _collect_handoff_evidence(self) -> dict:
        return {
            "branch": self._git_output(["branch", "--show-current"]) or "Detached HEAD",
            "status_short": self._git_output(["status", "--short"]),
            "diff_stat": self._git_output(["diff", "--stat"]),
            "changed_files": self._git_output(["diff", "--name-only"]).splitlines(),
            "latest_commit": self._git_output(["rev-parse", "--short", "HEAD"]),
        }

    def _run_git(self, args: list[str]) -> dict:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=settings.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except Exception as e:
            return {"returncode": 1, "stdout": "", "stderr": str(e)}
        return {
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    def _git_output(self, args: list[str]) -> str:
        result = self._run_git(args)
        return result["stdout"] if result["returncode"] == 0 else ""

    def _append_agent_handoff_context(
        self,
        work_item_id: str,
        agent_name: str,
        response: str,
        evidence: dict | None = None,
        completion: dict | None = None,
        agent_run_id: str | None = None,
    ) -> None:
        completion = completion if completion is not None else self._parse_agent_completion(response)
        context = self._format_handoff_context(agent_name, response, completion, evidence or {})
        metadata = self._handoff_context_metadata(completion, evidence or {})
        result = self.ticket_tools.append_shared_context(
            work_item_id,
            agent_name,
            context,
            agent_run_id=agent_run_id,
            metadata=metadata,
        )
        logger.info("Shared context append result for work item #%s: %s", work_item_id, result)

    def _handoff_context_metadata(self, completion: dict | None, evidence: dict) -> dict:
        metadata = {
            "status": (completion or {}).get("status", "UNKNOWN"),
            "latest_commit": evidence.get("latest_commit") or "",
            "changed_files": evidence.get("changed_files") or [],
        }
        if (completion or {}).get("artifacts"):
            metadata["artifact_count"] = len((completion or {}).get("artifacts") or [])
        return metadata

    def _parse_agent_completion(self, response: str) -> dict | None:
        completion, _error = self._decode_agent_completion(response)
        return completion

    def _decode_agent_completion(self, response: str) -> tuple[dict | None, str]:
        marker = "[AGENT_RUN_COMPLETE]"
        if marker not in response:
            return None, f"Agent response did not contain the required {marker} marker."
        payload = response.split(marker, 1)[1].strip()
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as e:
            return None, f"Completion payload was not valid JSON: {e.msg}."
        if not isinstance(parsed, dict):
            return None, "Completion payload must be a JSON object."
        try:
            completion = AgentCompletion.model_validate(parsed)
        except ValidationError as e:
            return None, f"Completion payload failed validation: {e.errors(include_url=False)}"
        return completion.model_dump(mode="json", exclude_none=True), ""

    def _normalize_agent_completion(self, agent_name: str, response: str) -> tuple[dict, dict]:
        completion, error = self._decode_agent_completion(response)
        if completion:
            return completion, {}

        failed_completion = AgentCompletion(
            status="FAILED",
            summary=f"{agent_name} returned an invalid completion handoff.",
            details=error,
            blockers=["A valid completion handoff is required before the workflow can continue."],
        )
        diagnostics = AgentRunDiagnostics(
            failure_kind="invalid_completion",
            error_type="CompletionValidationError",
            error_message=error,
        )
        return (
            failed_completion.model_dump(mode="json", exclude_none=True),
            diagnostics.model_dump(mode="json"),
        )

    def _exception_completion(self, agent_name: str, error: Exception) -> dict:
        return AgentCompletion(
            status="FAILED",
            summary=f"Error delegating to {agent_name}: {error}",
            details="The delegated agent did not complete because its execution raised an exception.",
            blockers=["Review the agent-run diagnostics before retrying this phase."],
        ).model_dump(mode="json", exclude_none=True)

    def _truncate_raw_response(self, response: str) -> tuple[str, bool]:
        value = str(response or "")
        if len(value) <= MAX_RAW_AGENT_RESPONSE_CHARS:
            return value, False
        return value[:MAX_RAW_AGENT_RESPONSE_CHARS], True

    def _format_handoff_context(
        self,
        agent_name: str,
        response: str,
        completion: dict | None,
        evidence: dict,
    ) -> str:
        lines = [f"Delegated agent: {agent_name}"]
        if completion:
            lines.extend([
                f"Status: {completion.get('status', 'UNKNOWN')}",
                f"Summary: {completion.get('summary', '')}",
            ])
            if completion.get("details"):
                lines.extend(["", "Details:", str(completion["details"])])
            for label, key in (
                ("Decisions", "decisions"),
                ("Blockers", "blockers"),
                ("Artifacts", "artifacts"),
            ):
                values = completion.get(key) or []
                if values:
                    lines.append("")
                    lines.append(f"{label}:")
                    for value in values:
                        lines.append(f"- {value}")
        else:
            lines.extend([
                "Status: UNKNOWN",
                "",
                "Raw response:",
                response,
            ])

        lines.extend([
            "",
            "Automatic evidence:",
            f"- Branch: {evidence.get('branch') or 'Unknown'}",
            f"- Latest commit: {evidence.get('latest_commit') or 'Unknown'}",
            f"- Git status: {evidence.get('status_short') or 'Clean'}",
            f"- Changed files: {', '.join(evidence.get('changed_files') or []) or 'None'}",
            f"- Diff stat: {evidence.get('diff_stat') or 'No diff'}",
        ])
        return "\n".join(lines)

    def _get_system_message(self) -> str:
        return f"""You are the Orchestrator Agent for the Ariadne V-Model.
Your goal is to manage the backlog, translate user requests into structured work items, and coordinate the development lifecycle with maximum efficiency and minimal token waste.

### Backlog Management
1. Analyze user input. Answer questions directly or ask for clarification if a request is vague.
2. When creating or updating work items, follow professional Agile standards.
3. Always check work item comments for open points, questions, or pending feedback before marking work complete.
4. For new features or bugs, structure descriptions with a user story, acceptance criteria, technical context, and traceability where applicable.
5. When acting on existing work items, check the current state with `get_work_item` if IDs, status, comments, artifacts, or ownership are unclear.
6. Use `list_work_items` to discover available work items.
7. Use `activate_work_item` when the user wants to work with a work item in this conversation but has not asked you to delegate it to another agent.
8. Always report the exact result of your actions to the user.

### SURGICAL DELEGATION PROTOCOL:
When using `delegate_to_agent`, you MUST structure your `task_description` as follows:
1. **Goal:** Clear statement of the desired outcome.
2. **Knowledge Summary:** Summarize what you already know (e.g., from comments or previous steps) so the agent doesn't have to re-discover it.
3. **Primary Manifests (Discovery-by-Query):** List the EXACT files or directories the agent should examine. 
    *   **Crucial:** If this is a refinement task (updating an existing requirement or design), you MUST discover the existing file path first. Do this by checking the `Links` attached to the parent work item using `get_work_item`, or by listing likely artifact directories with `list_files`. Do NOT assume the file is named after the work item ID. Provide the discovered file path here.
    *   Tell them: "Your primary context is in [Files]. You should prioritize these. If you identify a dependency outside this list, you may explore it, but you MUST state your reasoning in your 'Thought'."
4. **Expected Artifact:** Define the expected outcome (e.g., "Updated docs/requirements/REQ-005.md and attached to the work item via add_link").

### Responsibilities:
1. **Monitor:** Track work item status and progress in the project management system.
2. **Delegate:** Sequential dispatch: REQ -> ARCH -> DEV -> TEST -> QA.
3. **Validate:** Ensure agents return [SUCCESS] and produce the required artifacts.
4. **Escalations:** If an agent is blocked or hits a recursion limit, analyze the failure and provide narrower instructions.

### V-Model Sequence:
- [REQ] Requirements Agent (Output: docs/requirements/REQ-*.md)
- [ARCH] Architect Agent (Output: docs/design/ARCH-*.md)
- [DEV] Developer Agent (Output: Source Code)
- [TEST] Tester Agent (Output: tests/*.py)
- [QA] QA Agent (Output: Review Labels/Comments)

### Available Tools:
{self.tool_docs}
"""
