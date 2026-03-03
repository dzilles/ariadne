import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Use a global variable for the active ticket ID to ensure it is shared across threads
# in the current execution process.
_active_ticket_id: Optional[str] = None

def set_active_ticket_id(ticket_id: str):
    """Sets the active ticket ID for the current execution."""
    global _active_ticket_id
    logger.info(f"Setting active ticket context to #{ticket_id}")
    _active_ticket_id = ticket_id

def get_active_ticket_id() -> Optional[str]:
    """Retrieves the active ticket ID."""
    global _active_ticket_id
    return _active_ticket_id
