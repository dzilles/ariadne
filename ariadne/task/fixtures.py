"""Generate synthetic system-test tasks through the real task APIs."""
from pathlib import Path

from ariadne._util import loads, object_fields, text, strings, enum_value
from ariadne.errors import Error
from .model import TaskUpdate, SearchQuery, RecordEvent, normalize_file
from .store import TaskStore
from .vectors import DemoEmbedder


def validate_plan(plan):
    # Validate the whole plan before creating an output database.
    try:
        object_fields(plan, ["project_id", "repository_id", "tasks"])
        text(plan["project_id"], "project_id")
        text(plan["repository_id"], "repository_id")
        if not isinstance(plan["tasks"], list):
            raise Error.invalid("tasks must be a list")
        for task in plan["tasks"]:
            object_fields(task, ["key", "title", "description", "acceptance_criteria", "tags", "blocked_by", "state", "files"], ["related_to", "state_reason"])
            for name in ("key", "title", "description"):
                text(task[name], name)
            for name in ("acceptance_criteria", "tags", "blocked_by"):
                strings(task[name], name, unique=name != "acceptance_criteria")
            strings(task.get("related_to", []), "related_to", unique=True)
            enum_value(task["state"], ("draft", "ready", "in_progress", "blocked", "completed"), "fixture state")
            if "state_reason" in task:
                text(task["state_reason"], "state_reason")
            if not isinstance(task["files"], list):
                raise Error.invalid("files must be a list")
            for file in task["files"]:
                object_fields(file, ["path", "comment"])
                normalize_file({"repository_id": plan["repository_id"], **file})
    except Error as exc:
        raise Error("INVALID_FIXTURE", exc.message) from exc
    tasks = plan["tasks"]
    if len(tasks) < 20:
        raise Error("INVALID_FIXTURE", "Example plan requires at least 20 tasks")
    keys = {task["key"]: i for i, task in enumerate(tasks)}
    if len(keys) != len(tasks):
        raise Error("INVALID_FIXTURE", "Task keys must be unique")
    for index, task in enumerate(tasks):
        dependencies = task["blocked_by"]
        if index and not dependencies or len(set(dependencies)) != len(dependencies):
            raise Error("INVALID_FIXTURE", "Tasks must depend on unique earlier tasks")
        for dependency in dependencies:
            if dependency not in keys or keys[dependency] >= index:
                raise Error("INVALID_FIXTURE", "Missing, forward, or cyclic dependency")
            if task["state"] != "draft" and tasks[keys[dependency]]["state"] != "completed":
                raise Error("INVALID_FIXTURE", "Active tasks require completed prerequisites")
        if any(key not in keys or key == task["key"] for key in task.get("related_to", [])):
            raise Error("INVALID_FIXTURE", "Invalid related task")
        if task["state"] == "blocked" and not task.get("state_reason", "").strip():
            raise Error("INVALID_FIXTURE", "Blocked task needs a reason")
    return plan


def populate(store, plan):
    validate_plan(plan)
    project, repository = plan["project_id"], plan["repository_id"]
    if store.orchestrator().search_tasks(SearchQuery(project, limit=1)):
        raise Error("INVALID_FIXTURE", "Seed project already exists")
    embedder = DemoEmbedder()
    store.register_embedding_model(embedder.model())
    ids = {}
    for spec in plan["tasks"]:
        task = store.orchestrator().create_task(project, f"{spec['key']}: {spec['title']}\n\n{spec['description']}", [spec["key"], "system-fixture", *spec["tags"]])
        ids[spec["key"]] = task.id
    for position, spec in enumerate(plan["tasks"]):
        task_id, key, state = ids[spec["key"]], spec["key"], spec["state"]
        files = [{"repository_id": repository, "path": file["path"], "comment": file["comment"]} for file in spec["files"]]
        relations = [{"task_id": ids[target], "kind": kind} for kind, targets in [("blocked_by", spec["blocked_by"]), ("related_to", spec.get("related_to", []))] for target in targets]
        store.orchestrator().update_task(task_id, TaskUpdate(acceptance_criteria=spec["acceptance_criteria"], relations=relations, files=files,
            links=[{"url": f"https://example.com/android-ai-chat/tasks/{key}", "label": f"{key} planning reference", "comment": "Fictional URL used to exercise reference storage; no network access is required."}]))
        store.orchestrator().add_note(task_id, f"Synthetic system-test task; no Android application has actually been built. Planned prerequisites: {', '.join(spec['blocked_by']) or 'none'}.")

        def emit(suffix, **change):
            return store.recorder().record_event(RecordEvent(f"fixture-{key}-{suffix}", task_id, change, f"fixture-run-{key}"))

        if state == "draft":
            continue
        emit("ready", type="workflow_status_changed", sequence=1, status="ready")
        if state == "ready":
            continue
        emit("started", type="workflow_status_changed", sequence=2, status="in_progress", current_step="code")
        emit("usage", type="usage_recorded", model_call_id=f"fixture-call-{key}", input_tokens=700 + position * 13, output_tokens=200 + position * 5)
        emit("files", type="files_observed", files=[{**file, "comment": None, "relation": "modified" if state == "completed" else "consulted"} for file in files])
        if state == "completed":
            emit("git", type="git_recorded", reference={"repository_id": repository, "commit_hash": f"{position + 1:040x}", "kind": "development"})
            emit("agent-result", type="agent_result_recorded", summary=f"Synthetic fixture result: {spec['title']} passed its mock acceptance checks.")
            emit("finished", type="workflow_finished", sequence=3, status="completed", result_summary=f"Synthetic completion: {spec['title']}. Mock acceptance checks passed; no real implementation is included.", elapsed_time_ms=4000 + position * 1500)
        elif state == "blocked":
            emit("blocked", type="workflow_status_changed", sequence=3, status="blocked", current_step="code", state_reason=spec["state_reason"])
        elif state == "in_progress":
            emit("checkpoint", type="git_recorded", reference={"repository_id": repository, "commit_hash": f"{1000 + position:040x}", "kind": "checkpoint", "development_head": f"{6:040x}"})
        else:
            raise Error("INVALID_FIXTURE", "Unsupported fixture state")
    while not store.index_status(project).complete:
        if not store.index_pending(embedder, 200).applied:
            raise Error("INVALID_FIXTURE", "Fixture indexing made no progress")
    return {"project_id": project, "tasks": len(ids), "dependency_edges": sum(len(spec["blocked_by"]) for spec in plan["tasks"]), "indexed_sources": store.index_status(project).ready}


def seed_database(output, plan_path):
    output = Path(output)
    plan = validate_plan(loads(Path(plan_path).read_text()))
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(output, "xb"):
            pass
    except FileExistsError as exc:
        raise Error("OUTPUT_EXISTS", "Choose a new database path; existing files are never overwritten") from exc
    with TaskStore(output) as store:
        return populate(store, plan)
