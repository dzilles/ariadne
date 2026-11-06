# Ariadne: implementation and next steps

Start with the [architecture diagram](architecture.md). The active prototype uses Python 3.11+ and SQLite, with no third-party runtime dependencies. The previous Rust code and UI are preserved in [deprecated/rust](../deprecated/README.md).

## Implemented

| Module | Responsibility |
| --- | --- |
| [Tasks](modules/task-module.md) | Task definitions, references, dependencies, history, automatic event recording, usage, and vector search. |
| [Configuration](modules/configuration-module.md) | Validated profiles, API connections, versioned prompts, workflow definitions, and immutable snapshots. |
| [LLM access](modules/llm-module.md) | Shared asynchronous model API, OpenRouter adapter, streaming, tools, cancellation, and usage. |
| [Application interface](modules/interaction-module.md) | Session-scoped commands and bounded asynchronous event channels. |
| [Orchestrator](modules/orchestrator-module.md) | Persistent conversations and a project-scoped task/discovery tool loop. |

There is no active UI. The task/configuration JSON-line CLI supports scripting; the headless application API supports a future frontend. See the [offline application example](../examples/headless_flow.py).

Only orchestrator conversations are saved as chat history. Task results, progress, references, and usage belong in the task database. Display events and partial model output are temporary.

## Planned execution loop

The orchestrator selects work and a saved workflow. Each step follows **workflow engine → context service → agent runtime → workflow engine**. Workers focus on their assignment. The runtime observes tool calls and sends recording events; the workflow engine records state changes. Workers receive no task-management tools.

The context service will combine project instructions, task references, previous step results, and retrieved material within a context budget. Start with explicit links and task search. An LLM-assisted retriever or graph index can be added when needed.

The [Git tracker](modules/git-tracking-module.md) will keep development history and automatic checkpoints separate. The task recorder already stores both kinds of Git reference; repository capture itself remains unimplemented.

Agent execution, workflow scheduling/resumption, project knowledge storage, context assembly, repository tools, and Git capture are future work. Configuration validates workflow definitions but does not execute them.

## Open decisions

- How should the new UI connect to the headless application?
- May workers ask the user questions directly, or should questions pass through the orchestrator?
- Which project instructions are mandatory, and how should retrieval fit the remaining context budget?
- How should concurrent workers isolate repository changes?
- What scheduling, approval, retry, and recovery policies should workflows use?
- When should embedding jobs run in the background, and which real embedding model should replace demo vectors?
