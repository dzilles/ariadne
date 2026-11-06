import logging
import os
import subprocess

from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.application.delegation import (
    DelegationRejectedError,
    DelegationService,
)
from src.ariadne.policies.registry import build_agent_tools, build_tool_docs
from src.ariadne.tools.tool_wrapper import wrap_tools_with_error_handling
from src.ariadne.config.settings import settings
from src.ariadne.infrastructure.container import DependencyRegistry

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """
    Orchestrator Agent responsible for coordinating the workflow and high-level planning.
    """

    def __init__(self, ticket_tools=None, file_tools=None, delegation_service=None):
        super().__init__()

        try:
            self.ticket_tools = ticket_tools or DependencyRegistry.get_work_item_tools()
            self.file_tools = file_tools or DependencyRegistry.get_file_tools()
            self.delegation_service = delegation_service or DelegationService(
                self.ticket_tools
            )
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
        self.tools = wrap_tools_with_error_handling(
            raw_tools,
            agent_name="Orchestrator",
        )

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
            return self._search_codebase_without_rg(
                query, directory, file_glob, max_results
            )
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
                                matches.append(
                                    f"{rel_path}:{line_number}:{line.rstrip()}"
                                )
                                if len(matches) >= max_results:
                                    return (
                                        "\n".join(matches)
                                        + f"\n... truncated after {max_results} matches"
                                    )
                except UnicodeDecodeError:
                    continue
                except OSError:
                    continue
        return "\n".join(matches) if matches else "No matches found."

    def delegate_to_agent(
        self,
        agent_name: str,
        work_item_id: str,
        task_description: str,
    ) -> str:
        """Delegate a work item to a specialist through the coordination service."""
        try:
            result = self.delegation_service.delegate(
                agent_name,
                work_item_id,
                task_description,
            )
        except DelegationRejectedError as error:
            return str(error)
        except Exception as error:
            logger.exception(
                "Failed to coordinate delegation to %s for work item #%s",
                agent_name,
                work_item_id,
            )
            return f"Error delegating to {agent_name}: {error}"

        return result.to_orchestrator_message()

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
    *   **Crucial:** If this is a refinement task (updating an existing requirement or design), you MUST discover the existing file path first. Do this by checking the artifacts attached to the current work item using `get_work_item`, or by listing likely artifact directories with `list_files`. Do NOT assume the file is named after the work item ID. Provide the discovered file path here.
    *   Tell them: "Your primary context is in [Files]. You should prioritize these. If you identify a dependency outside this list, you may explore it, but you MUST state your reasoning in your 'Thought'."
4. **Expected Artifact:** Define the expected outcome (e.g., "Update docs/requirements/REQ-005.md and report it in the typed completion artifacts").

### Responsibilities:
1. **Monitor:** Track work item status and progress in the project management system.
2. **Delegate:** Route only to the specialist that owns the work item's current workflow state.
3. **Validate:** Use typed specialist completion and durable finalization results; do not infer success from prose alone.
4. **Escalations:** If an agent is blocked or hits a recursion limit, analyze the failure and provide narrower instructions.

### V-Model Sequence:
- [REQ] Requirements Agent (Output: docs/requirements/REQ-*.md)
- [QM] Quality Manager (Output: analysis gate decision)
- [ARCH] Architect Agent (Output: docs/design/ARCH-*.md)
- [DEV] Developer Agent (Output: Source Code)
- [TEST] Tester Agent (Output: tests/*.py)
- [QA] QA Agent (Output: Review Labels/Comments)

### Available Tools:
{self.tool_docs}
"""
