from __future__ import annotations

import copy
from pathlib import Path

from ariadne._util import (connect, transaction, dumps, loads, new_id, now,
                           text, strings, integer, enum_value, object_fields, optional_text)
from ariadne.errors import Error
from .model import (Task, TaskSummary, TaskUpdate, SearchQuery, RecordEvent, EventReceipt,
                    HistoryEntry, TaskStatus, normalize_link, normalize_file, normalize_git, file_identity)


class TaskStore:
    def __init__(self, path=":memory:"):
        self.db = connect(path)
        try:
            with transaction(self.db):
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    for statement in Path(__file__).with_name("schema.sql").read_text().split(";"):
                        if statement.strip():
                            self.db.execute(statement)
                elif version != 1:
                    raise Error("SCHEMA_VERSION", f"Unsupported task database version {version}")
        except BaseException:
            self.close()
            raise

    @classmethod
    def open(cls, path=":memory:"):
        return cls(path)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def orchestrator(self):
        return OrchestratorApi(self)

    def recorder(self):
        return RecordingApi(self)

    def _get(self, task_id):
        text(task_id, "task ID")
        row = self.db.execute("SELECT data FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise Error("NOT_FOUND", f"Task {task_id} does not exist")
        return Task.from_dict(loads(row[0]))

    def _save(self, task):
        from .vectors import sync_sources
        integer(task.version + 1, "task version", 1)
        task.version += 1
        task.updated_at = now()
        self.db.execute("UPDATE tasks SET data=?,version=? WHERE id=?", (dumps(task), task.version, task.id))
        sync_sources(self.db, task)

    def _history(self, task, source, data, run_id=None, event_id=None):
        self.db.execute("INSERT INTO history(id,task_id,timestamp,source,run_id,data) VALUES(?,?,?,?,?,?)",
                        (event_id or new_id(), task.id, now(), source, run_id or "", dumps(data)))

    # The vector implementation shares this database and transaction protocol.
    def register_embedding_model(self, model):
        from .vectors import register_model
        return register_model(self, model)

    def pending_embeddings(self, model, limit=20):
        from .vectors import pending_embeddings
        return pending_embeddings(self, model, limit)

    def complete_embedding(self, job, vector):
        from .vectors import complete_embedding
        return complete_embedding(self, job, vector)

    def index_pending(self, embedder=None, limit=20):
        from .vectors import index_pending, DemoEmbedder
        return index_pending(self, embedder or DemoEmbedder(), limit)

    def index_status(self, project_id, model="demo-token-hash-v1"):
        from .vectors import index_status
        return index_status(self, project_id, model)

    def rebuild_embeddings(self, model="demo-token-hash-v1"):
        from .vectors import rebuild_embeddings
        return rebuild_embeddings(self, model)

    def semantic_search(self, query, embedder=None):
        from .vectors import semantic_search, DemoEmbedder
        return semantic_search(self, query, embedder or DemoEmbedder())


class OrchestratorApi:
    def __init__(self, store):
        self.store = store

    def create_task(self, project_id, description, tags=None):
        text(project_id, "project_id")
        text(description, "description")
        tags = copy.deepcopy(strings([] if tags is None else tags, "tags", unique=True))
        from .vectors import sync_sources
        with transaction(self.store.db):
            stamp = now()
            task = Task(new_id(), project_id, stamp, stamp, 1, description, tags=tags)
            self.store.db.execute("INSERT INTO tasks(id,project_id,version,data) VALUES(?,?,1,?)", (task.id, project_id, dumps(task)))
            sync_sources(self.store.db, task)
            self.store._history(task, "orchestrator", {"type": "task_created", "task": task.to_dict()})
            return task

    def get_task(self, task_id):
        return self.store._get(task_id)

    def update_task(self, task_id, changes=None, **kwargs):
        if changes is not None and kwargs:
            raise Error.invalid("Supply a TaskUpdate or keyword changes, not both")
        if changes is not None and not isinstance(changes, (TaskUpdate, dict)):
            raise Error.invalid("Expected a TaskUpdate or change object")
        changes = TaskUpdate.from_dict(changes if isinstance(changes, dict) else kwargs) if not isinstance(changes, TaskUpdate) else copy.deepcopy(changes)
        with transaction(self.store.db):
            task = self.store._get(task_id)
            if changes.expected_version is not None:
                integer(changes.expected_version, "expected_version", 1)
                if changes.expected_version != task.version:
                    raise Error("CONFLICT", f"Reload task; current version is {task.version}")
            if changes.description is not None or changes.acceptance_criteria is not None:
                if task.status in ("in_progress", "completed", "cancelled"):
                    raise Error("TASK_BUSY", "Move task to draft, ready, or blocked before editing its goal")
                task.result_summary = None
            if changes.description is not None:
                task.description = text(changes.description, "description")
            if changes.acceptance_criteria is not None:
                task.acceptance_criteria = strings(changes.acceptance_criteria, "acceptance criteria")
            if changes.tags is not None:
                task.tags = strings(changes.tags, "tags", unique=True)
            if changes.relations is not None:
                self._validate_relations(task, changes.relations)
                task.relations = copy.deepcopy(changes.relations)
            if changes.links is not None:
                if not isinstance(changes.links, list):
                    raise Error.invalid("links must be a list")
                links, urls = [], set()
                for item in changes.links:
                    link = normalize_link(item)
                    if link["url"] in urls:
                        raise Error.invalid("Duplicate link URL")
                    urls.add(link["url"])
                    old = next((ref for ref in task.links if ref["url"] == link["url"]), None)
                    links.append({"id": old["id"] if old else new_id(), **link})
                task.links = links
            if changes.files is not None:
                if not isinstance(changes.files, list):
                    raise Error.invalid("files must be a list")
                files = [ref for ref in task.files if ref["relation"] != "linked"]
                seen = set()
                for item in changes.files:
                    file = normalize_file(item)
                    identity = file_identity(file)
                    if identity in seen:
                        raise Error.invalid("Duplicate explicit file reference")
                    seen.add(identity)
                    old = next((ref for ref in task.files if ref["relation"] == "linked" and file_identity(ref) == identity), None)
                    files.append({"id": old["id"] if old else new_id(), "relation": "linked", **file})
                task.files = files
            self.store._save(task)
            self.store._history(task, "orchestrator", {"type": "task_updated", "version": task.version, "changes": changes.to_dict()})
            return task

    def _validate_relations(self, task, relations):
        if not isinstance(relations, list):
            raise Error.invalid("relations must be a list")
        for relation in relations:
            object_fields(relation, ["task_id", "kind"])
            enum_value(relation["kind"], ("blocked_by", "related_to"), "relation kind")
            target = self.store._get(relation["task_id"])
            if target.id == task.id or target.project_id != task.project_id:
                raise Error.invalid("Relations must target another task in the same project")
            if relation["kind"] == "blocked_by":
                pending, seen = [target.id], set()
                while pending:
                    current = pending.pop()
                    if current == task.id:
                        raise Error.invalid("blocked_by relations must not form a cycle")
                    if current not in seen:
                        seen.add(current)
                        pending.extend(r["task_id"] for r in self.store._get(current).relations if r["kind"] == "blocked_by")

    def annotate_reference(self, task_id, reference_id, comment):
        text(reference_id, "reference ID")
        text(comment, "comment", empty=True)
        with transaction(self.store.db):
            task = self.store._get(task_id)
            reference = next((ref for ref in task.links + task.files + task.git_refs if ref["id"] == reference_id), None)
            if reference is None:
                raise Error("NOT_FOUND", "Reference does not belong to this task")
            reference["comment"] = comment
            self.store._save(task)
            self.store._history(task, "orchestrator", {"type": "reference_annotated", "reference_id": reference_id, "comment": comment})
            return task

    def add_note(self, task_id, text):
        from ariadne._util import text as validate_text
        validate_text(text, "note")
        with transaction(self.store.db):
            task = self.store._get(task_id)
            self.store._save(task)
            self.store._history(task, "orchestrator", {"type": "note_added", "text": text})
            return task

    def get_history(self, task_id, limit=20):
        integer(limit, "limit", 1, 200)
        self.store._get(task_id)
        rows = self.store.db.execute("SELECT * FROM history WHERE task_id=? ORDER BY sequence DESC LIMIT ?", (task_id, limit)).fetchall()
        return [HistoryEntry(row["sequence"], row["id"], task_id, row["timestamp"], row["source"], row["run_id"] or None, loads(row["data"])) for row in reversed(rows)]

    def search_tasks(self, query):
        query = SearchQuery.from_dict(query) if isinstance(query, dict) else query
        query.validate()
        rows = self.store.db.execute("SELECT data FROM tasks WHERE project_id=? ORDER BY json_extract(data,'$.updated_at') DESC,id", (query.project_id,))
        results = []
        for row in rows:
            task = Task.from_dict(loads(row[0]))
            if not matches_filters(task, query):
                continue
            if query.text is not None:
                content = [task.description, *task.acceptance_criteria, *task.tags, task.result_summary or ""]
                for ref in task.links:
                    content.extend(ref.get(k) or "" for k in ("url", "label", "comment"))
                for ref in task.files:
                    content.extend(ref.get(k) or "" for k in ("path", "symbol", "comment"))
                content.extend(loads(r[0]).get("text", "") for r in self.store.db.execute("SELECT data FROM history WHERE task_id=? AND json_extract(data,'$.type')='note_added'", (task.id,)))
                if query.text.lower() not in " ".join(content).lower():
                    continue
            results.append(TaskSummary.of(task))
            if len(results) >= query.limit:
                break
        return results


def matches_filters(task, query):
    return task.project_id == query.project_id and (query.status is None or task.status == query.status) and (query.tag is None or query.tag in task.tags)


def normalize_change(value):
    if not isinstance(value, dict):
        raise Error.invalid("Event change must be an object")
    kind = value.get("type")
    fields = {
        "workflow_status_changed": (["sequence", "status"], ["current_step", "state_reason"]),
        "workflow_finished": (["sequence", "status", "result_summary", "elapsed_time_ms"], []),
        "files_observed": (["files"], []), "agent_result_recorded": (["summary"], []),
        "git_recorded": (["reference"], []), "usage_recorded": (["model_call_id"], ["input_tokens", "output_tokens"]),
    }
    if kind not in fields:
        raise Error.invalid("Unknown recorded event type")
    required, optional = fields[kind]
    change = copy.deepcopy(object_fields(value, ["type", *required], optional))
    for key in optional:
        change.setdefault(key, None)
    if kind.startswith("workflow_"):
        integer(change["sequence"], "workflow sequence", 1)
        enum_value(change["status"], TaskStatus, "status")
    if kind == "workflow_status_changed":
        optional_text(change["current_step"])
        optional_text(change["state_reason"])
    if kind == "workflow_finished":
        text(change["result_summary"], "result summary")
        integer(change["elapsed_time_ms"], "duration")
    if kind == "files_observed":
        if not isinstance(change["files"], list):
            raise Error.invalid("Observed files must be a list")
        files = []
        for raw in change["files"]:
            raw = object_fields(raw, ["repository_id", "path", "relation"], ["commit_hash", "symbol", "start_line", "end_line", "comment"])
            enum_value(raw["relation"], ("consulted", "modified"), "observed file relation")
            files.append({**normalize_file({k: v for k, v in raw.items() if k != "relation"}), "relation": raw["relation"]})
        change["files"] = files
    if kind == "git_recorded":
        change["reference"] = normalize_git(change["reference"])
    if kind == "agent_result_recorded":
        text(change["summary"], "agent result")
    if kind == "usage_recorded":
        text(change["model_call_id"], "model_call_id")
        for key in ("input_tokens", "output_tokens"):
            if change[key] is not None:
                integer(change[key], key, maximum=2**64 - 1)
    return change


class RecordingApi:
    def __init__(self, store):
        self.store = store

    def record_event(self, event):
        event = RecordEvent.from_dict(event.to_dict() if isinstance(event, RecordEvent) else event)
        text(event.id, "event ID")
        if event.run_id is not None:
            text(event.run_id, "run_id")
        event.change = normalize_change(event.change)
        change, db = event.change, self.store.db
        kind = change["type"]
        with transaction(db):
            task = self.store._get(event.task_id)
            old = db.execute("SELECT data FROM recorded_events WHERE id=?", (event.id,)).fetchone()
            if old:
                if loads(old[0]) != event.to_dict():
                    raise Error("CONFLICT", "Event ID reused with different content")
                return EventReceipt(event.id, True, task.version)
            if kind.startswith("workflow_"):
                current = db.execute("SELECT workflow_sequence FROM tasks WHERE id=?", (task.id,)).fetchone()[0]
                if change["sequence"] != current + 1:
                    raise Error("CONFLICT", f"Expected workflow sequence {current + 1}; retry missing events in order")
                transition(task.status, change["status"])
                db.execute("UPDATE tasks SET workflow_sequence=? WHERE id=?", (change["sequence"], task.id))
            if kind == "workflow_status_changed":
                if change["status"] == "completed":
                    raise Error.invalid("Use workflow_finished for completion and its result")
                task.status, task.current_step, task.state_reason = change["status"], change["current_step"], change["state_reason"]
            elif kind == "workflow_finished":
                if change["status"] not in ("completed", "blocked", "cancelled") or not event.run_id:
                    raise Error.invalid("Workflow outcome requires a run ID and completed, blocked, or cancelled status")
                if db.execute("SELECT 1 FROM workflow_outcomes WHERE task_id=? AND run_id=?", (task.id, event.run_id)).fetchone():
                    raise Error("CONFLICT", "This run already has a workflow outcome")
                durations = [r[0] for r in db.execute("SELECT elapsed_ms FROM workflow_outcomes WHERE task_id=?", (task.id,))]
                task.elapsed_time_ms = integer(sum(durations) + change["elapsed_time_ms"], "duration total")
                db.execute("INSERT INTO workflow_outcomes VALUES(?,?,?)", (task.id, event.run_id, change["elapsed_time_ms"]))
                task.status, task.current_step = change["status"], None
                task.result_summary = change["result_summary"]
                task.state_reason = None if task.status == "completed" else task.result_summary
            elif kind == "files_observed":
                for file in change["files"]:
                    if not any(ref["relation"] == file["relation"] and file_identity(ref) == file_identity(file) for ref in task.files):
                        task.files.append({"id": new_id(), **file})
            elif kind == "git_recorded":
                ref = change["reference"]
                if not any(all(old.get(k) == v for k, v in ref.items()) and old.get("run_id") == event.run_id for old in task.git_refs):
                    task.git_refs.append({"id": new_id(), "run_id": event.run_id, "comment": None, **ref})
            elif kind == "usage_recorded":
                counts = [change["input_tokens"], change["output_tokens"]]
                previous = db.execute("SELECT data FROM usage_calls WHERE task_id=? AND call_id=?", (task.id, change["model_call_id"])).fetchone()
                if previous and loads(previous[0]) != counts:
                    raise Error("CONFLICT", "Model-call ID reused with different usage")
                db.execute("INSERT OR IGNORE INTO usage_calls VALUES(?,?,?)", (task.id, change["model_call_id"], dumps(counts)))
                measurements = [loads(r[0]) for r in db.execute("SELECT data FROM usage_calls WHERE task_id=?", (task.id,))]
                totals = [None if any(m[i] is None for m in measurements) else integer(sum(m[i] for m in measurements), "token total", maximum=2**64 - 1) for i in (0, 1)]
                task.input_tokens, task.output_tokens = totals
            self.store._save(task)
            source = "workflow_engine" if kind.startswith("workflow_") else "git_tracker" if kind == "git_recorded" else "runtime"
            self.store._history(task, source, change, event.run_id, event.id)
            db.execute("INSERT INTO recorded_events VALUES(?,?,?)", (event.id, task.id, dumps(event)))
            return EventReceipt(event.id, False, task.version)


def transition(old, new):
    allowed = {"draft": {"ready", "cancelled"}, "ready": {"in_progress", "cancelled"},
               "in_progress": {"in_progress", "blocked", "completed", "cancelled"},
               "blocked": {"ready", "in_progress", "cancelled"}, "completed": {"ready"}, "cancelled": {"ready"}}
    if new not in allowed.get(old, set()):
        raise Error("INVALID_TRANSITION", f"Cannot move task from {old} to {new}")
