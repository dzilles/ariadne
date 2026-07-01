import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.application.commands import APPLICATION_COMMANDS


def test_application_commands_include_project_commands():
    names = {command.name for command in APPLICATION_COMMANDS}

    assert {
        "save",
        "load",
        "history",
        "clearhistory",
        "secret",
        "copy",
    }.issubset(names)
