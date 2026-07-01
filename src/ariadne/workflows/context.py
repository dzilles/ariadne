"""Backward-compatible workflow context imports."""

from src.ariadne.runtime.context import (
    get_active_ticket_id,
    get_active_work_item_id,
    notify_active_work_item_changed,
    set_active_work_item_change_callback,
    set_active_ticket_id,
    set_active_work_item_id,
)

__all__ = [
    "get_active_ticket_id",
    "get_active_work_item_id",
    "notify_active_work_item_changed",
    "set_active_work_item_change_callback",
    "set_active_ticket_id",
    "set_active_work_item_id",
]
