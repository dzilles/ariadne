import logging
import contextvars
from typing import Optional

logger = logging.getLogger(__name__)

# Use ContextVar to ensure the active work item ID is safely isolated
# across concurrent async tasks and threads.
_active_work_item_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_active_work_item_id", default=None
)


def set_active_work_item_id(work_item_id: str):
    """Set the active work item ID for the current execution context."""
    logger.info(f"Setting active work item context to #{work_item_id}")
    _active_work_item_id.set(work_item_id)


def get_active_work_item_id() -> Optional[str]:
    """Retrieve the active work item ID for the current execution context."""
    return _active_work_item_id.get()


def set_active_ticket_id(ticket_id: str):
    """Backward-compatible alias for set_active_work_item_id."""
    set_active_work_item_id(ticket_id)


def get_active_ticket_id() -> Optional[str]:
    """Backward-compatible alias for get_active_work_item_id."""
    return get_active_work_item_id()
