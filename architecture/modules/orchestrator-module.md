# Headless orchestrator

[Main architecture](../architecture.md)

Implemented in [`ariadne/orchestrator/`](../../ariadne/orchestrator/__init__.py), with tests in `tests/orchestrator/`. No UI is included. Coordinates conversation and task tools. Agent/workflow execution and repository tools remain future work.

## Flow

1. An application client submits a user message through the application interface.
2. The orchestrator loads its conversation and fixed configuration snapshot.
3. The shared LLM module streams a response or returns tool calls.
4. Application code validates and executes enabled task/discovery tools, saves their results, and calls the model again when needed.
5. The completed reply is saved; the client receives the turn outcome and refreshes task data.

Task tools are bound to the conversation's project. The model cannot choose another project or call internal recorder/indexer operations. Profile/workflow discovery reads the conversation's snapshot. Tools are limited by the profile's `max_tool_calls` setting, capped at 100 per turn; the default is 12.

## Interface

| Operation | Purpose |
| --- | --- |
| `ConversationStore.create(...)`, `get(id)`, `list(project_id)` | Create and restore orchestrator conversations. |
| `await Orchestrator.turn(...)` | Run one message/tool loop using shared LLM access and display events. |
| `app.submit(session_id, payload)` | Queue frontend commands; the application dispatches chat/cancellation. |
| `TaskTools.definitions(...)`, `call(...)` | Expose the selected profile's task/discovery tools with project scoping. |

Every conversation pins its profile, model, and configuration snapshot. Supported prompt inputs are `project_id`, `project_summary`, and `user_request` (a reference to the conversation's user messages). New conversations pick up configuration edits. Concurrent sessions have independent model context; one turn can run per session.

## Persistence

Only orchestrator conversations are saved as chat history, in `<configuration-root>/orchestrator.sqlite`: user messages, completed assistant messages, the orchestrator's tool dialogue, and call metadata. System prompts and opaque provider continuation data are stored for later model calls and omitted from the public UI view.

Task facts/results remain in the task database. The application event stream and partial text fragments are temporary. Agent/tool conversations have no separate persistent chat store. Task recorder extensions can capture additional execution details as those modules are built.

Conversation writes use version checks. Tool requests are saved before execution; results are saved afterward. Startup marks interrupted turns and closes unanswered tool requests with an interruption result. A crash between a task write and saving its tool result remains ambiguous; the application never replays that tool automatically. Only one application instance may use a configuration root at a time.

## Application lifecycle

Initialize an empty configuration with `python3 -m ariadne init --model MODEL`. For live model calls, supply `OPENROUTER_API_KEY` in the environment.

Start with `await Application.start(Options(...))`. The returned application exposes conversation creation/loading, task summaries, command submission, and `app.interface` for event subscriptions. Use `async with` or `await app.close()` to release channels, active calls, and the application lock. One turn may run per session; up to 16 sessions can run concurrently.

The [offline example](../../examples/headless_flow.py) demonstrates the complete lifecycle with a deterministic model adapter and real task writes. A future UI can use this API without changing the module boundaries. No HTTP routes, browser assets, or interactive terminal frontend are included.
