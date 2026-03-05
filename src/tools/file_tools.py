import os
import logging
from src.workflows.enforcement import jit_vmodel_guard
from src.configuration.config import settings

logger = logging.getLogger(__name__)

class FileAgentTools:
    """
    File system interaction tools for AI Agents.
    """
    
    def _resolve_path(self, path: str) -> str:
        """Resolves the given path against the sandbox directory if sandbox mode is enabled."""
        if not settings.sandbox_mode:
            return path
            
        # Remove leading slashes so os.path.join treats it as relative
        clean_path = str(path).lstrip('/')
        # If it's a dot or explicitly current dir, map to sandbox root
        if clean_path in ('.', ''):
            return settings.sandbox_dir
            
        resolved = os.path.join(settings.sandbox_dir, clean_path)
        return resolved
    
    def read_file(self, file_path: str) -> str:
        """
        Reads the content of a file.
        
        Args:
            file_path: The relative or absolute path to the file.
        """
        actual_path = self._resolve_path(file_path)
        msg_prefix = "[Tool (SANDBOX)" if settings.sandbox_mode else "[Tool"
        msg = f"{msg_prefix}: read_file called for '{file_path}' (resolved: {actual_path})]"
        print(f"\n{msg}")
        logger.info(msg)
        
        if not os.path.exists(actual_path):
            return f"Error: File '{file_path}' not found."
            
        try:
            with open(actual_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    @jit_vmodel_guard
    def write_file(self, file_path: str, content: str) -> str:
        """
        Writes content to a file. Overwrites if exists, creates directories if needed.
        
        Args:
            file_path: The path where the file should be saved.
            content: The text content to write.
        """
        actual_path = self._resolve_path(file_path)
        msg_prefix = "[Tool (SANDBOX)" if settings.sandbox_mode else "[Tool"
        msg = f"{msg_prefix}: write_file called for '{file_path}' (resolved: {actual_path})]"
        print(f"\n{msg}")
        logger.info(msg)
        
        try:
            directory = os.path.dirname(actual_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
                
            with open(actual_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Success: File written to '{file_path}'"
        except Exception as e:
            return f"Error writing file: {e}"

    def list_files(self, directory: str = ".") -> str:
        """
        Lists files in a directory.
        """
        actual_path = self._resolve_path(directory)
        msg_prefix = "[Tool (SANDBOX)" if settings.sandbox_mode else "[Tool"
        msg = f"{msg_prefix}: list_files called for '{directory}' (resolved: {actual_path})]"
        print(f"\n{msg}")
        logger.info(msg)
        
        if not os.path.exists(actual_path):
            return f"Error: Directory '{directory}' not found."
            
        try:
            files = os.listdir(actual_path)
            return "\n".join(files) if files else "Directory is empty."
        except Exception as e:
            return f"Error listing directory: {e}"

    def search_files(self, directory: str, pattern: str) -> str:
        """
        Searches for files matching a pattern within a directory.
        Supports glob patterns (e.g., 'ARCH-*.md').
        """
        actual_path = self._resolve_path(directory)
        msg_prefix = "[Tool (SANDBOX)" if settings.sandbox_mode else "[Tool"
        msg = f"{msg_prefix}: search_files called in '{directory}' (resolved: {actual_path}) for '{pattern}']"
        print(f"\n{msg}")
        logger.info(msg)
        
        import fnmatch
        matches = []
        try:
            for root, _, files in os.walk(actual_path):
                for file in files:
                    if fnmatch.fnmatch(file, pattern) or pattern in file:
                         # Return paths relative to the requested directory, not the sandbox root
                         rel_path = os.path.relpath(os.path.join(root, file), start=settings.sandbox_dir)
                         matches.append(rel_path)
            if not matches:
                 return "No files found matching pattern."
            return "\n".join(matches)
        except Exception as e:
            return f"Error searching files: {e}"

    def get_tool_descriptions(self) -> str:
        return """
### File System Tools
*   `read_file(file_path)`: Reads the content of a file.
*   `write_file(file_path, content)`: Writes content to a file (overwrites if exists).
*   `list_files(directory)`: Lists files in a directory.
*   `search_files(directory, pattern)`: Finds files matching a name pattern.
"""
