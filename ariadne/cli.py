"""Machine-readable task/configuration CLI. Interactive UI is deliberately deferred."""
import argparse
import sqlite3
import sys

from ._util import dumps, loads, object_fields, to_data
from .errors import Error
from .task import TaskStore, RecordEvent, DemoEmbedder
from .task import tools as task_tools
from .configuration import ConfigurationStore, Prompt
from .configuration import tools as config_tools


def execute_task(store, role, request):
    if not isinstance(request, dict):
        raise Error.invalid("Request must be an object")
    name = request.get("op")
    args = {k: v for k, v in request.items() if k != "op"}
    internal = {"record_event": "recorder", "index_pending": "indexer", "index_status": "indexer", "rebuild_index": "indexer"}
    if not isinstance(name, str) or name not in {*internal, *(item["name"] for item in task_tools.tool_definitions())}:
        raise Error.invalid("Unknown task operation")
    if role != internal.get(name, "orchestrator"):
        raise Error("FORBIDDEN", "Operation is unavailable to the selected API role")
    if name not in internal:
        return task_tools.call(store, name, args)
    if name == "record_event":
        object_fields(args, ["event"])
        return store.recorder().record_event(RecordEvent.from_dict(args["event"]))
    if name == "index_pending":
        object_fields(args, [], ["limit"])
        return store.index_pending(DemoEmbedder(), args.get("limit", 20))
    if name == "index_status":
        object_fields(args, ["project_id"])
        return store.index_status(args["project_id"])
    object_fields(args)
    store.rebuild_embeddings()
    return {"queued": True}


def execute_configuration(store, role, request):
    fields = {"list_profiles": ([], ["component"]), "get_profile": (["id"], []), "get_prompt": (["id"], []), "get_workflow": (["id"], []),
              "list_workflows": ([], []), "list_providers": ([], []), "get_provider": (["id"], []), "validate": ([], []),
              "save_prompt": (["id", "text"], ["variables", "expected_revision"]), "save_profile": (["profile"], ["expected_revision"]),
              "save_provider": (["provider"], ["expected_revision"]), "save_workflow": (["definition"], ["expected_revision"]),
              "replace_configuration": (["configuration"], ["expected_revision"]), "create_snapshot": ([], []), "get_snapshot": (["id"], []),
              "render_profile": (["id"], ["variables", "snapshot_id"])}
    name = request.get("op") if isinstance(request, dict) else None
    if name not in fields:
        raise Error.invalid("Unknown configuration operation")
    required, optional = fields[name]
    object_fields(request, ["op", *required], optional)
    args = {k: v for k, v in request.items() if k != "op"}
    if name.startswith("save_") or name == "replace_configuration":
        if role != "editor":
            raise Error("FORBIDDEN", "Configuration changes require editor role")
        revision = args.pop("expected_revision", None)
        if name == "save_prompt": result = store.save_prompt(Prompt.from_dict(args), revision)
        elif name == "save_profile": result = store.save_profile(args["profile"], revision)
        elif name == "save_provider": result = store.save_provider(args["provider"], revision)
        elif name == "save_workflow": result = store.save_workflow(args["definition"], revision)
        else: result = store.replace_configuration(args["configuration"], revision)
        return {"revision": result}
    if name == "validate": return store.status()
    if name == "list_profiles": return store.list_profiles(args.get("component"))
    if name in ("get_profile", "get_prompt", "get_workflow", "get_provider", "get_snapshot"): return getattr(store, name)(args["id"])
    if name in ("list_workflows", "list_providers"): return getattr(store, name)()
    if name == "create_snapshot":
        snapshot = store.create_snapshot()
        return {"id": snapshot.id, "revision": snapshot.revision}
    if name == "render_profile":
        snapshot_id = args.get("snapshot_id")
        if snapshot_id is not None:
            snapshot = store.get_snapshot(snapshot_id)
            revision, config = snapshot.revision, snapshot.configuration
        else:
            revision, config = store.load()
        return {"snapshot_id": snapshot_id, "revision": revision, "resolved": config.render_profile(args["id"], args.get("variables", {}))}


def json_lines(execute):
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            result = execute(loads(line))
            response = {"ok": True, "result": to_data(result)}
        except Error as exc:
            response = {"ok": False, "error": exc.to_dict()}
        except (ValueError, TypeError) as exc:
            response = {"ok": False, "error": Error.invalid(str(exc)).to_dict()}
        except (OSError, sqlite3.Error) as exc:
            response = {"ok": False, "error": Error("DATABASE_ERROR" if isinstance(exc, sqlite3.Error) else "IO_ERROR", str(exc)).to_dict()}
        print(dumps(response), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ariadne headless APIs. No UI is included in the Python prototype.")
    subs = parser.add_subparsers(dest="module", required=True)
    task = subs.add_parser("task", help="Task JSON-line API")
    task.add_argument("--db", default="ariadne.sqlite")
    task.add_argument("--role", choices=["orchestrator", "recorder", "indexer"], default="orchestrator")
    task.add_argument("--tools", action="store_true")
    config = subs.add_parser("config", help="Configuration JSON-line API")
    config.add_argument("--root", default=".ariadne")
    config.add_argument("--role", choices=["reader", "editor"], default="reader")
    config.add_argument("--tools", action="store_true")
    init = subs.add_parser("init", help="Initialize OpenRouter configuration in an empty directory")
    init.add_argument("--root", default=".ariadne")
    init.add_argument("--model", required=True)
    seed = subs.add_parser("seed", help="Generate a synthetic Android task database")
    seed.add_argument("output")
    seed.add_argument("--plan", default="tests/system/fixtures/android-chat-tasks.json")
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0].startswith("--") and args[0] not in ("--help", "-h"):
        args.insert(0, "task")
    options = parser.parse_args(args)
    try:
        if options.module == "task":
            if options.tools:
                print(dumps(task_tools.tool_definitions(), pretty=True))
                return 0
            with TaskStore(options.db) as store:
                store.register_embedding_model(DemoEmbedder().model())
                json_lines(lambda request: execute_task(store, options.role, request))
        elif options.module == "config":
            if options.tools:
                print(dumps(config_tools.tool_definitions(), pretty=True))
                return 0
            store = ConfigurationStore(options.root)
            json_lines(lambda request: execute_configuration(store, options.role, request))
        elif options.module == "init":
            from .orchestrator import initialize
            initialize(options.root, options.model)
            print(dumps({"ok": True, "root": options.root}))
        else:
            from .task.fixtures import seed_database
            print(dumps(seed_database(options.output, options.plan), pretty=True))
        return 0
    except (Error, OSError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1
