"""History persistence for chat sessions.

This module provides functions to save and load agent chat history,
compatible with the existing agent history methods (get_history/load_history).
"""

import json
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default directory for history files
HISTORY_DIR = ".ariadne"


def get_history_filename(agent_name: str) -> str:
    """Get the history filename for an agent.

    Args:
        agent_name: The agent's name

    Returns:
        The path to the history file
    """
    # Sanitize agent name for use in filename
    safe_name = agent_name.lower().replace(" ", "_")
    return os.path.join(HISTORY_DIR, f"chat_history_{safe_name}.json")


def ensure_history_dir() -> None:
    """Ensure the history directory exists."""
    if not os.path.exists(HISTORY_DIR):
        os.makedirs(HISTORY_DIR)


def save_history(agent: Any, agent_name: str) -> bool:
    """Save the agent's chat history to a file.

    Args:
        agent: The agent instance with a get_history() method
        agent_name: The agent's name (used for filename)

    Returns:
        True if successful, False otherwise
    """
    if not hasattr(agent, "get_history"):
        logger.warning(f"Agent {agent_name} does not support history export")
        return False

    try:
        ensure_history_dir()
        filename = get_history_filename(agent_name)
        history = agent.get_history()

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

        logger.info(f"Saved {len(history)} messages to {filename}")
        return True

    except Exception as e:
        logger.error(f"Failed to save history for {agent_name}: {e}")
        return False


def load_history(agent: Any, agent_name: str) -> bool:
    """Load chat history from a file into the agent.

    Args:
        agent: The agent instance with a load_history() method
        agent_name: The agent's name (used for filename)

    Returns:
        True if successful, False if no history or error
    """
    if not hasattr(agent, "load_history"):
        logger.warning(f"Agent {agent_name} does not support history import")
        return False

    filename = get_history_filename(agent_name)

    if not os.path.exists(filename):
        logger.debug(f"No history file found for {agent_name}")
        return False

    try:
        with open(filename, "r", encoding="utf-8") as f:
            history = json.load(f)

        agent.load_history(history)
        logger.info(f"Loaded {len(history)} messages from {filename}")
        return True

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in history file {filename}: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to load history for {agent_name}: {e}")
        return False


def clear_history(agent_name: str) -> bool:
    """Delete the history file for an agent.

    Args:
        agent_name: The agent's name

    Returns:
        True if deleted or didn't exist, False on error
    """
    filename = get_history_filename(agent_name)

    if not os.path.exists(filename):
        return True

    try:
        os.remove(filename)
        logger.info(f"Deleted history file {filename}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete history file {filename}: {e}")
        return False


def has_history(agent_name: str) -> bool:
    """Check if an agent has saved history.

    Args:
        agent_name: The agent's name

    Returns:
        True if history file exists
    """
    filename = get_history_filename(agent_name)
    return os.path.exists(filename)


def get_history_summary(agent_name: str) -> dict | None:
    """Get a summary of the agent's saved history.

    Args:
        agent_name: The agent's name

    Returns:
        Dict with 'message_count' and 'last_modified', or None if no history
    """
    filename = get_history_filename(agent_name)

    if not os.path.exists(filename):
        return None

    try:
        stat = os.stat(filename)
        with open(filename, "r", encoding="utf-8") as f:
            history = json.load(f)

        return {
            "message_count": len(history),
            "last_modified": stat.st_mtime,
            "filename": filename,
        }
    except Exception:
        return None
