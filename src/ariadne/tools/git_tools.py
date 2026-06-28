import logging
from typing import List
from git import Repo, GitCommandError
from src.ariadne.config.settings import settings
from src.ariadne.workflows.enforcement import jit_vmodel_guard

logger = logging.getLogger(__name__)

class GitAgentTools:
    """
    Restricted Git tools for AI Agents to manage version control.
    Allows only specific, safe operations necessary for the V-Model lifecycle.
    """

    def __init__(self):
        """
        Initialize the Git wrapper using the project path from settings.
        """
        self.project_path = settings.sandbox_dir if settings.sandbox_mode else settings.project_path
        try:
            self.repo = Repo(self.project_path)
            logger.info(f"Git initialized for repo at {self.project_path}")
        except Exception as e:
            logger.error(f"Failed to initialize Git repo at {self.project_path}: {e}")
            raise

    def get_status(self) -> str:
        """
        Returns the current git status (changed files, untracked files).
        """
        try:
            return self.repo.git.status()
        except GitCommandError as e:
            return f"Error getting status: {e}"

    def get_current_branch(self) -> str:
        """
        Returns the name of the currently active branch.
        """
        try:
            return self.repo.active_branch.name
        except TypeError:
            return "Detached HEAD"
        except Exception as e:
            return f"Error getting branch: {e}"

    @jit_vmodel_guard
    def create_branch(self, branch_name: str) -> str:
        """
        Creates and checks out a new branch.
        """
        try:
            current = self.repo.active_branch
            new_branch = self.repo.create_head(branch_name)
            new_branch.checkout()
            logger.info(f"Created and checked out branch: {branch_name}")
            return f"Success: Created and switched to branch '{branch_name}' (from '{current.name}')"
        except GitCommandError as e:
            return f"Error creating branch '{branch_name}': {e}"
        except Exception as e:
            return f"Error: {e}"

    def checkout_branch(self, branch_name: str) -> str:
        """
        Switches to an existing branch.
        """
        try:
            self.repo.git.checkout(branch_name)
            logger.info(f"Checked out branch: {branch_name}")
            return f"Success: Switched to branch '{branch_name}'"
        except GitCommandError as e:
            return f"Error checking out branch '{branch_name}': {e}"

    @jit_vmodel_guard
    def add_files(self, files: List[str] = None) -> str:
        """
        Stages specific files or all files (if files=['.']).
        """
        try:
            if not files:
                return "Error: No files specified to add. Use ['.'] to add all."
            
            self.repo.index.add(files)
            logger.info(f"Staged files: {files}")
            return f"Success: Staged {len(files)} file(s)."
        except GitCommandError as e:
            return f"Error adding files: {e}"

    @jit_vmodel_guard
    def commit_changes(self, message: str) -> str:
        """
        Commits staged changes with a message.
        """
        try:
            if self.repo.is_dirty(index=True) or self.repo.untracked_files:
                 # Check if anything is staged
                 if self.repo.index.diff("HEAD"):
                    commit = self.repo.index.commit(message)
                    logger.info(f"Committed changes: {commit.hexsha[:7]} - {message}")
                    return f"Success: Committed changes. Hash: {commit.hexsha[:7]}"
                 else:
                    return "Error: No changes staged for commit. Use add_files first."
            else:
                return "Error: Working tree clean, nothing to commit."
        except GitCommandError as e:
            return f"Error committing: {e}"

    @jit_vmodel_guard
    def push_changes(self, remote_name: str = "origin") -> str:
        """
        Pushes the current branch to the remote.
        """
        try:
            branch = self.repo.active_branch.name
            remote = self.repo.remote(name=remote_name)
            info = remote.push(refspec=f"{branch}:{branch}")
            
            # Check push info
            summary = []
            for i in info:
                if i.flags & i.ERROR:
                    summary.append(f"Error pushing {i.local_ref.name}: {i.summary}")
                else:
                    summary.append(f"Pushed {i.local_ref.name}: {i.summary}")
            
            result = "\n".join(summary)
            logger.info(f"Push result: {result}")
            return f"Push complete:\n{result}"
        except ValueError:
            return f"Error: Remote '{remote_name}' does not exist."
        except GitCommandError as e:
            return f"Error pushing to {remote_name}: {e}"

    def get_tool_descriptions(self) -> str:
        return """
### Git Version Control Tools
*   `get_status()`: Checks repository state (changed/untracked files).
*   `get_current_branch()`: Returns the active branch name.
*   `create_branch(branch_name)`: Creates and switches to a new branch.
*   `checkout_branch(branch_name)`: Switches to an existing branch.
*   `add_files(files)`: Stages specific files (e.g., `['docs/REQ-1.md']`) or `['.']` for all.
*   `commit_changes(message)`: Commits staged changes.
*   `push_changes(remote_name)`: Pushes the current branch to origin.
"""