from dataclasses import dataclass

from ariadne._util import JsonModel, object_fields, text, dumps
from ariadne.errors import Error


@dataclass
class Command(JsonModel):
    command_id: str
    session_id: str
    payload: dict


@dataclass
class Source(JsonModel):
    component: str
    instance_id: str


@dataclass
class EventContext(JsonModel):
    command_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    call_id: str | None = None


@dataclass
class Event(JsonModel):
    event_id: str
    session_id: str
    sequence: int
    source: Source
    context: EventContext
    payload: dict


def validate_command(payload):
    kind = payload.get("type") if isinstance(payload, dict) else None
    fields = {"send_message": ["text"], "cancel_run": ["run_id"], "respond_to_input": ["request_id", "answer"]}
    if kind not in fields:
        raise Error.invalid("Unknown application command")
    object_fields(payload, ["type", *fields[kind]])
    if kind == "send_message":
        text(payload["text"], "message")
        if len(payload["text"].encode("utf-8")) > 65536:
            raise Error.invalid("Message exceeds 65536 bytes")
    else:
        text(payload["run_id" if kind == "cancel_run" else "request_id"], "target ID")
    dumps(payload)


def validate_event(payload):
    kind = payload.get("type") if isinstance(payload, dict) else None
    fields = {"message_started": ["message_id"], "message_delta": ["message_id", "text"],
              "message_finished": ["message_id", "text"], "activity_updated": ["label", "state"],
              "input_requested": ["request_id", "prompt", "answer_type"], "input_resolved": ["request_id"],
              "run_finished": ["outcome"], "error": ["error"]}
    if kind not in fields:
        raise Error.invalid("Unknown application event")
    object_fields(payload, ["type", *fields[kind]])
    for key in fields[kind]:
        if key != "error":
            text(payload[key], key, empty=key == "text")
    if kind == "error":
        error = payload["error"]
        object_fields(error, ["code", "message"], ["retryable"])
        text(error["code"], "error code")
        text(error["message"], "error message", empty=True)
        if "retryable" in error and type(error["retryable"]) is not bool:
            raise Error.invalid("Error retryable field must be boolean")
    dumps(payload)
