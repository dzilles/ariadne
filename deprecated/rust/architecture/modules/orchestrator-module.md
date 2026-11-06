# Orchestrator and chat

[Main architecture](../architecture.md)

Implemented in [`src/orchestrator/`](../../src/orchestrator/mod.rs), with frontends in `src/ui/` and tests in `tests/orchestrator/`. Coordinates conversation and task tools. Agent/workflow execution and repository tools remain future work.

## Flow

1. The CLI/UI submits a user message through the application interface.
2. The orchestrator loads its conversation and fixed configuration snapshot.
3. The shared LLM module streams a response or returns tool calls.
4. Application code validates and executes enabled task/discovery tools, saves their results, and calls the model again when needed.
5. The completed reply is saved; the UI receives the turn outcome and refreshes task data.

Task tools are bound to the conversation's project. The model cannot choose another project or call internal recorder/indexer operations. Profile/workflow discovery reads the conversation's snapshot. Tools are limited by the profile's `max_tool_calls` setting, capped at 100 per turn; the default is 12.

## Interface

| Operation | Purpose |
| --- | --- |
| `ConversationStore::create(...)`, `get(id)`, `list(project_id)` | Create and restore orchestrator conversations. |
| `Orchestrator::turn(...)` | Run one message/tool loop using shared LLM access and display events. |
| `Application::submit(session_id, command)` | Queue frontend commands; the application dispatches chat/cancellation. |
| `TaskTools::definitions(...)`, `call(...)` | Expose the selected profile's task/discovery tools with project scoping. |

Every conversation pins its profile, model, and configuration snapshot. Supported prompt inputs are `project_id`, `project_summary`, and `user_request` (a reference to the conversation's user messages). New conversations pick up configuration edits. Concurrent sessions have independent model context; one turn can run per session.

## Persistence

Only orchestrator conversations are saved as chat history, in `<configuration-root>/orchestrator.sqlite`: user messages, completed assistant messages, the orchestrator's tool dialogue, and call metadata. System prompts and opaque provider continuation data are stored for later model calls and omitted from the public UI view.

Task facts/results remain in the task database. The application event stream and partial text fragments are temporary. Agent/tool conversations have no separate persistent chat store. Task recorder extensions can capture additional execution details as those modules are built.

Conversation writes use version checks. Tool requests are saved before execution; results are saved afterward. Startup marks interrupted turns and closes unanswered tool requests with an interruption result. A crash between a task write and saving its tool result remains ambiguous; the application never replays that tool automatically. Only one application instance may use a configuration root at a time.

## Frontends

Run `cargo run -- chat --project PROJECT` for the browser UI at `http://127.0.0.1:8787`, or add `--terminal` for terminal chat. Initialize an empty configuration with `chat init --model MODEL` and set `OPENROUTER_API_KEY` before starting. See [startup instructions](../../README.md#chat-with-the-orchestrator).

The browser frontend serves embedded assets, accepts JSON commands, streams display events over SSE, restores conversation history, and lists up to 200 current project tasks. It renders model text literally. HTTP routes are `/api/status`, `/api/conversations`, `/api/conversations/{id}`, `/api/commands`, `/api/events/{id}`, and `/api/tasks`.

The server binds to loopback. POST requests require JSON and `X-Ariadne-Client: ui`; Host/Origin checks enforce same-origin access. This is a local prototype with no remote authentication or multi-user deployment.
