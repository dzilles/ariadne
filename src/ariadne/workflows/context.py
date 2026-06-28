"""Backward-compatible workflow context imports."""

from src.ariadne.runtime.context import (
    get_active_ticket_id,
    get_active_work_item_id,
    set_active_ticket_id,
    set_active_work_item_id,
)

__all__ = [
    "get_active_ticket_id",
    "get_active_work_item_id",
    "set_active_ticket_id",
    "set_active_work_item_id",
]
