# Ariadne

A modular LLM harness prototype in Python 3.11+. The current implementation is headless: task storage, configuration, shared model access, application events, and the orchestrator. A UI will be added separately.

The previous Rust implementation, including its UI, is preserved in [deprecated/rust](deprecated/README.md). Existing task databases and configuration files remain readable.

## Run locally

There are no third-party runtime dependencies. Run these commands from the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 -m examples.headless_flow
python3 -m examples.task_flow
```

The headless example runs a real orchestrator/tool loop with a deterministic offline model. It creates a task, streams application events, and saves the conversation in a temporary directory. No API key or network access is needed.

Optional installation with `python3 -m pip install .` adds the `ariadne` command, equivalent to `python3 -m ariadne`.

## Modules

| Module | Implementation | Details |
| --- | --- | --- |
| Tasks | [ariadne/task](ariadne/task/__init__.py) | [Data, APIs, recording, vectors](architecture/modules/task-module.md) |
| Configuration | [ariadne/configuration](ariadne/configuration/__init__.py) | [Profiles, prompts, snapshots](architecture/modules/configuration-module.md) |
| LLM access | [ariadne/llm](ariadne/llm/__init__.py) | [OpenRouter and adapter interface](architecture/modules/llm-module.md) |
| Application interface | [ariadne/interaction](ariadne/interaction/__init__.py) | [Session commands and events](architecture/modules/interaction-module.md) |
| Orchestrator | [ariadne/orchestrator](ariadne/orchestrator/__init__.py) | [Headless conversation/tool loop](architecture/modules/orchestrator-module.md) |

See the [architecture diagram](architecture/architecture.md) and [implementation status](architecture/technical-reference.md). Workflow execution, worker agents, context assembly, project knowledge, and automatic Git capture remain planned modules. Tasks can already record workflow, tool, usage, and separate development/checkpoint Git events.

## Task API

The CLI accepts one JSON request per line and returns an `ok/result` or `ok/error` envelope. It continues after a malformed request.

```sh
echo '{"op":"create_task","project_id":"demo","description":"Implement chat streaming","tags":["android"]}' |
  python3 -m ariadne task --db /tmp/ariadne-demo.sqlite
echo '{"op":"search_tasks","project_id":"demo","text":"streaming"}' |
  python3 -m ariadne task --db /tmp/ariadne-demo.sqlite
python3 -m ariadne task --tools
```

Task definitions use the default `orchestrator` role. Automatic updates require `--role recorder`; embedding jobs require `--role indexer`. The orchestrator's LLM tool list excludes both internal APIs. Workers receive task context without task-management tools.

## Vector search

The [system fixture](tests/system/README.md) contains 30 dependent Android AI-chat tasks with existing vectors. Copy it before experimenting:

```sh
cp tests/system/fixtures/android-chat.sqlite /tmp/android-chat-demo.sqlite
echo '{"op":"search_tasks","project_id":"android-ai-chat","text":"internet search citations","mode":"semantic","tag":"search","limit":5}' |
  python3 -m ariadne task --db /tmp/android-chat-demo.sqlite
```

After changing source text, process pending embeddings:

```sh
echo '{"op":"index_pending","limit":200}' |
  python3 -m ariadne task --db /tmp/android-chat-demo.sqlite --role indexer
```

The CLI and fixture use **deterministic token-hash demo vectors**, not learned semantic embeddings. Python applications can provide an `Embedder` implementation for a real embedding model. Task text, revisions, and pending jobs are committed together in SQLite; stale embedding results are rejected. Search reports index coverage.

## Configuration and OpenRouter

Initialize an empty configuration directory with an explicit model ID:

```sh
python3 -m ariadne init --root .ariadne --model '<OpenRouter model ID>'
echo '{"op":"list_profiles"}' | python3 -m ariadne config --root .ariadne
```

For live requests, supply `OPENROUTER_API_KEY` in the process environment. Configuration saves only `env:OPENROUTER_API_KEY`, never the resolved key. Configuration changes use the CLI's `--role editor`; discovery defaults to `reader`.

[examples/configuration.json](examples/configuration.json) includes agent profiles and a code → review → testing definition. To save and inspect it in an empty directory:

```sh
python3 -m examples.configuration_flow /tmp/ariadne-config-demo
```

## Future UI integration

Use `await Application.start(Options(...))`, create or load a conversation, subscribe through `app.interface.subscribe(session_id)`, and submit a `send_message` command. Consume events asynchronously and close the application when finished. [The offline example](examples/headless_flow.py) shows this complete flow; [the live LLM example](examples/llm_call.py) shows a standalone OpenRouter call.

Only orchestrator conversations are persisted as chat history, alongside configuration snapshots. Task facts, recorded execution results, and usage live in the task database. Live event streams are temporary.
