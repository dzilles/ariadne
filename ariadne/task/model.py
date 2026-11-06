from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypedDict, NotRequired

from ariadne._util import JsonModel, enum_value, object_fields, integer, text, optional_text
from ariadne.errors import Error


class TaskStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskRelation(TypedDict):
    task_id: str
    kind: str


class LinkInput(TypedDict):
    url: str
    label: NotRequired[str | None]
    comment: NotRequired[str | None]


class FileInput(TypedDict):
    repository_id: str
    path: str
    commit_hash: NotRequired[str | None]
    symbol: NotRequired[str | None]
    start_line: NotRequired[int | None]
    end_line: NotRequired[int | None]
    comment: NotRequired[str | None]


class GitInput(TypedDict):
    repository_id: str
    commit_hash: str
    kind: str
    development_head: NotRequired[str | None]


@dataclass
class Task(JsonModel):
    id: str
    project_id: str
    created_at: str
    updated_at: str
    version: int
    description: str
    acceptance_criteria: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    relations: list[TaskRelation] = field(default_factory=list)
    status: str = "draft"
    current_step: str | None = None
    state_reason: str | None = None
    result_summary: str | None = None
    links: list[dict] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    git_refs: list[dict] = field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    elapsed_time_ms: int | None = None


@dataclass
class TaskSummary(JsonModel):
    id: str
    project_id: str
    description: str
    status: str
    tags: list[str]
    updated_at: str

    @classmethod
    def of(cls, task: Task):
        return cls(**{key: getattr(task, key) for key in cls.__dataclass_fields__})


@dataclass
class TaskUpdate(JsonModel):
    expected_version: int | None = None
    description: str | None = None
    acceptance_criteria: list[str] | None = None
    tags: list[str] | None = None
    relations: list[TaskRelation] | None = None
    links: list[LinkInput] | None = None
    files: list[FileInput] | None = None


@dataclass
class SearchQuery(JsonModel):
    project_id: str
    text: str | None = None
    status: str | None = None
    tag: str | None = None
    limit: int = 20

    def validate(self):
        text(self.project_id, "project_id")
        optional_text(self.text)
        optional_text(self.tag)
        integer(self.limit, "limit", 1, 200)
        if self.status is not None:
            enum_value(self.status, TaskStatus, "status")


@dataclass
class HistoryEntry(JsonModel):
    sequence: int
    id: str
    task_id: str
    timestamp: str
    source: str
    run_id: str | None
    data: dict


@dataclass
class RecordEvent(JsonModel):
    id: str
    task_id: str
    change: dict
    run_id: str | None = None


@dataclass
class EventReceipt(JsonModel):
    id: str
    duplicate: bool
    task_version: int


def normalize_link(value):
    value = object_fields(value, ["url"], ["label", "comment"])
    text(value["url"], "URL")
    return {"url": value["url"], **{k: optional_text(value.get(k), k) for k in ["label", "comment"]}}


def normalize_file(value):
    value = object_fields(value, ["repository_id", "path"], ["commit_hash", "symbol", "start_line", "end_line", "comment"])
    text(value["repository_id"], "repository_id")
    path = text(value["path"], "path")
    if path.startswith(("/", "\\")) or ".." in path.replace("\\", "/").split("/"):
        raise Error.invalid("File paths must be repository-relative without '..'")
    start, end = value.get("start_line"), value.get("end_line")
    if start is not None or end is not None:
        integer(start, "start_line", 1)
        integer(end, "end_line", start)
    return {"repository_id": value["repository_id"], "path": path, "start_line": start, "end_line": end,
            **{k: optional_text(value.get(k), k) for k in ["commit_hash", "symbol", "comment"]}}


def normalize_git(value):
    value = object_fields(value, ["repository_id", "commit_hash", "kind"], ["development_head"])
    text(value["repository_id"], "repository_id")
    text(value["commit_hash"], "commit_hash")
    enum_value(value["kind"], ("development", "checkpoint"), "Git kind")
    head = optional_text(value.get("development_head"))
    if value["kind"] == "checkpoint":
        text(head, "checkpoint development_head")
    return {**value, "development_head": head}


def file_identity(value):
    return tuple(value.get(k) for k in ("repository_id", "path", "commit_hash", "symbol", "start_line", "end_line"))
