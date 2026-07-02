"""Settings command behavior behind the UI boundary."""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import Enum
from typing import Any, get_args, get_origin

from .ui_contract import CommandResult


def supports_settings_command(settings: Any | None) -> bool:
    """Return True when a settings object exposes Pydantic-style fields."""
    return bool(settings is not None and _model_fields(settings))


def _model_fields(settings: Any) -> dict[str, Any]:
    return getattr(type(settings), "model_fields", None) or getattr(
        settings,
        "model_fields",
        {},
    )


def get_settings_completions(settings: Any | None, context: str = "") -> list[str]:
    """Return field or value completions for the settings command."""
    if not supports_settings_command(settings):
        return []

    parts = context.split()
    if len(parts) == 0 or (len(parts) == 1 and not context.endswith(" ")):
        return list(_model_fields(settings).keys())

    field_name = parts[0]
    fields = _model_fields(settings)
    if field_name in fields:
        choices = _get_field_choices(fields[field_name])
        if choices:
            return choices
    return []


def handle_settings_command(
    settings: Any | None,
    args: str = "",
    on_change: Callable[[str, Any], None] | None = None,
) -> CommandResult:
    """Show or update settings and return a display-ready result."""
    if not supports_settings_command(settings):
        return CommandResult("No settings configured.", is_error=True)

    parts = args.split(maxsplit=1)
    field_name = parts[0] if parts else ""
    new_value = parts[1] if len(parts) > 1 else ""

    if not field_name:
        lines = ["**Settings:**\n"]
        for name, field_info in _model_fields(settings).items():
            current_str = _format_current_value(getattr(settings, name))
            lines.append(f"- `{name}` = {current_str}")
            if field_info.description:
                lines.append(f"  *{field_info.description}*")
            lines.append(f"  Type: {_get_field_type_name(field_info)}")
            lines.append("")

        lines.append("Use `/settings <field> <value>` to change a setting.")
        return CommandResult("\n".join(lines))

    fields = _model_fields(settings)
    if field_name not in fields:
        available = ", ".join(f"`{name}`" for name in fields.keys())
        return CommandResult(
            f"Unknown setting `{field_name}`. Available: {available}",
            is_error=True,
        )

    field_info = fields[field_name]
    if not new_value:
        current_str = _format_current_value(getattr(settings, field_name))
        lines = [
            f"**{field_name}**\n",
            f"Current value: {current_str}",
            f"Type: {_get_field_type_name(field_info)}",
            f"Description: {field_info.description or 'No description'}",
        ]
        choices = _get_field_choices(field_info)
        if choices:
            lines.append(f"Choices: {', '.join(choices)}")
        lines.append(f"\nUse `/settings {field_name} <value>` to change.")
        return CommandResult("\n".join(lines))

    try:
        parsed_value = _parse_value(field_info, new_value)
        setattr(settings, field_name, parsed_value)
        if on_change:
            on_change(field_name, parsed_value)
        return CommandResult(
            f"Changed `{field_name}` to {_format_current_value(parsed_value)}"
        )
    except (ValueError, TypeError) as e:
        return CommandResult(f"Invalid value: {e}", is_error=True)


def _format_current_value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return repr(value)


def _unwrap_optional(annotation: Any) -> tuple[Any, Any]:
    origin = get_origin(annotation)
    if origin is type(None) or str(origin) == "typing.Union":
        args = get_args(annotation)
        non_none = [arg for arg in args if arg is not type(None)]
        if non_none:
            annotation = non_none[0]
            origin = get_origin(annotation)
    return annotation, origin


def _get_field_type_name(field_info: Any) -> str:
    annotation, origin = _unwrap_optional(field_info.annotation)

    if str(origin) == "typing.Literal":
        return f"Literal{list(get_args(annotation))}"
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return f"Enum{[item.value for item in annotation]}"
    if annotation is str:
        return "str"
    if annotation is int:
        return "int"
    if annotation is float:
        return "float"
    if annotation is bool:
        return "bool"
    if origin is list:
        return "list"
    if origin is dict:
        return "dict"
    return str(annotation).replace("typing.", "")


def _get_field_choices(field_info: Any) -> list[str] | None:
    annotation, origin = _unwrap_optional(field_info.annotation)

    if str(origin) == "typing.Literal":
        return [str(choice) for choice in get_args(annotation)]
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return [str(item.value) for item in annotation]
    if annotation is bool:
        return ["true", "false"]
    return None


def _parse_value(field_info: Any, value_str: str) -> Any:
    annotation, origin = _unwrap_optional(field_info.annotation)

    if str(origin) == "typing.Literal":
        choices = get_args(annotation)
        for choice in choices:
            if str(choice).lower() == value_str.lower():
                return choice
        raise ValueError(f"Must be one of: {list(choices)}")

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        for item in annotation:
            if (
                str(item.value).lower() == value_str.lower()
                or item.name.lower() == value_str.lower()
            ):
                return item
        raise ValueError(f"Must be one of: {[item.value for item in annotation]}")

    if annotation is bool:
        if value_str.lower() in ("true", "1", "yes", "on"):
            return True
        if value_str.lower() in ("false", "0", "no", "off"):
            return False
        raise ValueError("Must be true or false")
    if annotation is int:
        return int(value_str)
    if annotation is float:
        return float(value_str)
    if annotation is str:
        return value_str

    try:
        return json.loads(value_str)
    except json.JSONDecodeError:
        return value_str
