"""Persistence for user-adjustable Ariadne settings."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

SETTINGS_DIR = ".ariadne"
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "user_settings.json")


def load_user_settings() -> dict[str, Any]:
    """Load user settings from disk."""
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load user settings: %s", e)
        return {}


def save_user_settings(data: dict[str, Any]) -> bool:
    """Save user settings to disk."""
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error("Failed to save user settings: %s", e)
        return False


def update_user_setting(field_name: str, value: Any) -> bool:
    """Persist a single user setting value."""
    user_settings = load_user_settings()
    user_settings[field_name] = value
    return save_user_settings(user_settings)
