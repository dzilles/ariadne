import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic import BaseModel, Field

from src.ariadne.application.settings_commands import (
    get_settings_completions,
    handle_settings_command,
)


class FakeSettings(BaseModel):
    verbose: bool = Field(default=False, description="Show extra detail")
    mode: Literal["fast", "safe"] = "fast"


def test_settings_command_lists_fields():
    result = handle_settings_command(FakeSettings())

    assert not result.is_error
    assert "`verbose` = False" in result.message
    assert "Show extra detail" in result.message


def test_settings_command_updates_value_and_notifies_callback():
    settings = FakeSettings()
    changes = []

    result = handle_settings_command(
        settings,
        "verbose true",
        lambda name, value: changes.append((name, value)),
    )

    assert not result.is_error
    assert settings.verbose is True
    assert changes == [("verbose", True)]


def test_settings_command_rejects_invalid_bool():
    result = handle_settings_command(FakeSettings(), "verbose maybe")

    assert result.is_error
    assert "Must be true or false" in result.message


def test_settings_completions_return_fields_and_choices():
    settings = FakeSettings()

    assert "verbose" in get_settings_completions(settings)
    assert get_settings_completions(settings, "mode ") == ["fast", "safe"]
