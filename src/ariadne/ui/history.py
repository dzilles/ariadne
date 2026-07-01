"""Compatibility imports for chat history persistence."""

from src.ariadne.application.history import (
    HISTORY_DIR,
    HistoryError,
    HistoryFormatError,
    HistoryNotFoundError,
    clear_history,
    ensure_history_dir,
    get_history_filename,
    get_history_summary,
    has_history,
    load_history,
    save_history,
)

__all__ = [
    "HISTORY_DIR",
    "HistoryError",
    "HistoryFormatError",
    "HistoryNotFoundError",
    "clear_history",
    "ensure_history_dir",
    "get_history_filename",
    "get_history_summary",
    "has_history",
    "load_history",
    "save_history",
]
