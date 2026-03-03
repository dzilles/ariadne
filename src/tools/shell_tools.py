import subprocess
import logging
from src.workflows.enforcement import jit_vmodel_guard

logger = logging.getLogger(__name__)

class ShellAgentTools:
    """
    Shell execution tools for AI Agents.
    """
    
    @jit_vmodel_guard
    def run_shell_command(self, command: str) -> str:
        """
        Executes a shell command. Use this to run tests, linters, or syntax checks.
        
        Args:
            command: The bash command to execute.
        """
        msg = f"[Tool: run_shell_command called for '{command}']"
        print(f"\n{msg}")
        logger.info(msg)
        
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=120
            )
            output = f"Exit Code: {result.returncode}\n"
            if result.stdout:
                output += f"STDOUT:\n{result.stdout}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr}\n"
            return output
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 120 seconds."
        except Exception as e:
            return f"Error executing command: {e}"

    def get_tool_descriptions(self) -> str:
        return """
### Shell Tools
*   `run_shell_command(command)`: Executes a shell command (e.g., `python -m py_compile file.py` or `pytest`).
"""
