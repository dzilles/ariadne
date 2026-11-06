import copy
from pathlib import Path

from ariadne._util import loads, object_fields
from ariadne.errors import Error
from .model import TaskUpdate, SearchQuery
from .vectors import DemoEmbedder


def tool_definitions():
    return loads(Path(__file__).with_name("tools.json").read_text())


def validate_arguments(value, schema, path="arguments"):
    expected = schema.get("type")
    types = expected if isinstance(expected, list) else [expected] if expected else []
    actual = "null" if value is None else "boolean" if type(value) is bool else "integer" if type(value) is int else "number" if type(value) is float else "string" if isinstance(value, str) else "array" if isinstance(value, list) else "object" if isinstance(value, dict) else "invalid"
    if types and actual not in types and not (actual == "integer" and "number" in types):
        raise Error.invalid(f"{path}: expected {types}")
    if "enum" in schema and value not in schema["enum"]:
        raise Error.invalid(f"{path}: unsupported value")
    if actual in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"] or "maximum" in schema and value > schema["maximum"]:
            raise Error.invalid(f"{path}: outside allowed range")
    if actual == "object":
        props, required = schema.get("properties", {}), schema.get("required", [])
        if schema.get("additionalProperties") is False:
            object_fields(value, required, props.keys() - set(required))
        elif not set(required) <= value.keys():
            raise Error.invalid(f"{path}: missing required fields")
        for name, item in value.items():
            if name in props:
                validate_arguments(item, props[name], f"{path}.{name}")
    if actual == "array" and "items" in schema:
        for item in value:
            validate_arguments(item, schema["items"], f"{path}[]")


def call(store, name, arguments):
    definition = next((tool for tool in tool_definitions() if tool["name"] == name), None)
    if definition is None:
        raise Error("FORBIDDEN", "Unknown or internal task tool")
    validate_arguments(arguments, definition["input_schema"])
    arguments = copy.deepcopy(arguments)
    api = store.orchestrator()
    if name == "create_task": return api.create_task(**arguments)
    if name == "update_task":
        task_id = arguments.pop("id")
        return api.update_task(task_id, TaskUpdate.from_dict(arguments))
    if name == "get_task": return api.get_task(arguments["id"])
    if name == "get_history": return api.get_history(arguments["id"], arguments.get("limit", 20))
    if name == "add_note": return api.add_note(**arguments)
    if name == "annotate_reference": return api.annotate_reference(**arguments)
    if name == "search_tasks":
        mode = arguments.pop("mode", "keyword")
        query = SearchQuery.from_dict(arguments)
        return store.semantic_search(query, DemoEmbedder()) if mode == "semantic" else api.search_tasks(query)
    raise Error("FORBIDDEN", "Unavailable tool")
