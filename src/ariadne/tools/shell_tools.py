import subprocess
import logging
from src.ariadne.workflows.enforcement import jit_vmodel_guard
from src.ariadne.config.settings import settings

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
        if settings.sandbox_mode:
            # Wrap the command to execute inside the docker container
            # We use base64 encoding to avoid complex escaping issues
            import base64
            encoded_cmd = base64.b64encode(command.encode('utf-8')).decode('utf-8')
            docker_cmd = f"docker exec -w /workspace ariadne-sandbox bash -c 'echo {encoded_cmd} | base64 -d | bash'"
            actual_command = docker_cmd
            msg_prefix = "[Tool (SANDBOX): run_shell_command"
        else:
            actual_command = command
            msg_prefix = "[Tool: run_shell_command"

        msg = f"{msg_prefix} called for '{command}']"
        print(f"\n{msg}")
        logger.info(msg)
        
        try:
            result = subprocess.run(
                actual_command, shell=True, capture_output=True, text=True, timeout=120
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
