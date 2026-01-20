import os
import glob
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

class FileAgentTools:
    """
    File system interaction tools for AI Agents.
    """
    
    def read_file(self, file_path: str) -> str:
        """
        Reads the content of a file.
        
        Args:
            file_path: The relative or absolute path to the file.
        """
        msg = f"[Tool: read_file called for '{file_path}']"
        print(f"\n{msg}")
        logger.info(msg)
        
        if not os.path.exists(file_path):
            return f"Error: File '{file_path}' not found."
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    def write_file(self, file_path: str, content: str) -> str:
        """
        Writes content to a file. Overwrites if exists, creates directories if needed.
        
        Args:
            file_path: The path where the file should be saved.
            content: The text content to write.
        """
        msg = f"[Tool: write_file called for '{file_path}']"
        print(f"\n{msg}")
        logger.info(msg)
        
        try:
            directory = os.path.dirname(file_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
                
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Success: File written to '{file_path}'"
        except Exception as e:
            return f"Error writing file: {e}"

    def list_files(self, directory: str = ".") -> str:
        """
        Lists files in a directory.
        """
        msg = f"[Tool: list_files called for '{directory}']"
        print(f"\n{msg}")
        logger.info(msg)
        
        if not os.path.exists(directory):
            return f"Error: Directory '{directory}' not found."
            
        try:
            files = os.listdir(directory)
            return "\n".join(files) if files else "Directory is empty."
        except Exception as e:
            return f"Error listing directory: {e}"

    def search_files(self, pattern: str) -> str:
        """
        Finds files matching a glob pattern (e.g., 'docs/**/*.md').
        """
        msg = f"[Tool: search_files called with pattern='{pattern}']"
        print(f"\n{msg}")
        logger.info(msg)
        
        try:
            # recursive=True allows ** to match subdirectories
            files = glob.glob(pattern, recursive=True)
            return "\n".join(files) if files else "No files found matching pattern."
        except Exception as e:
            return f"Error searching files: {e}"
