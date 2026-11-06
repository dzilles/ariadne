from pathlib import Path

from ariadne._util import loads
from ariadne.errors import Error
from ariadne.task.tools import validate_arguments


def tool_definitions():
    return loads(Path(__file__).with_name("tools.json").read_text())


def call(configuration, name, arguments):
    definition = next((item for item in tool_definitions() if item["name"] == name), None)
    if definition is None:
        raise Error("FORBIDDEN", "Only profile/workflow discovery tools are available")
    validate_arguments(arguments, definition["input_schema"])
    if name == "list_profiles":
        return [p for p in configuration.profiles.values() if arguments.get("component") is None or p.component == arguments["component"]]
    if name == "list_workflows":
        return list(configuration.workflows.values())
    group = configuration.profiles if name == "get_profile" else configuration.workflows
    if arguments["id"] not in group:
        raise Error("NOT_FOUND", "Configured profile/workflow does not exist")
    return group[arguments["id"]]
