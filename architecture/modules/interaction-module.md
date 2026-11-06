# Application interface

[Main architecture](../architecture.md)

Implemented in [`ariadne/interaction/`](../../ariadne/interaction/__init__.py), with tests in `tests/interaction/`. Connects a future CLI/UI to application modules through typed commands and bounded event channels inside one application.

## Responsibilities

A future frontend will render messages and activity from multiple modules. Modules publish structured events through this interface rather than writing to the terminal. User actions arrive as commands and are dispatched to their owning module.

The interface routes communication. The orchestrator owns conversation and coordination; the workflow engine owns execution; the task module owns task records. Displaying an event does not update a task. Runtime and workflow code still use the separate task recording API for automatic bookkeeping.

## Interface

| Operation | Caller | Purpose |
| --- | --- | --- |
| `submit(session_id, payload) -> command_id` | CLI/UI | Submit a message, cancellation, or answer to an input request. Acknowledgment means accepted, not finished. |
| `await publish(session_id, source, context, payload)` | Application modules | Publish user-facing messages, streamed text, activity, or errors. |
| `subscribe(session_id) -> Subscription` | CLI/UI | Receive events for the selected conversation and its associated work. |

Initial command types: `send_message`, `cancel_run`, and `respond_to_input`. Each has a unique `command_id`, a `session_id`, and typed payload. Cancellation targets a run; input responses target a `request_id`. Handlers validate commands and report their outcome through events.

`Interface(capacity=128)` creates the channels; the dispatcher awaits `receive_command()`. Subscribe with an asynchronous context manager and consume events with `async for`. The initial application dispatches chat and cancellation; workflow input responses return `UNSUPPORTED_OPERATION` until a handler exists. Other modules can publish through the same interface on the application event loop.

Initial event types: `message_started`, `message_delta`, `message_finished`, `activity_updated`, `input_requested`, `input_resolved`, `run_finished`, and `error`. These are display events, separate from the LLM provider's event types.

## Shared event data

| Field | Type | Purpose |
| --- | --- | --- |
| `event_id` | ID | Unique event identity. |
| `session_id` | ID | Conversation receiving the event. |
| `sequence` | Integer | Order assigned by the interface within that session. |
| `source` | Component kind and instance ID | Identifies the orchestrator, agent, tool, or other publisher. |
| `command_id`, `run_id`, `task_id`, `call_id` | Optional IDs | Associate output with the request and work that produced it. |
| `payload` | Typed event data | Message content, progress, input request, result, or error. |

Streamed message events also carry a stable `message_id`; input requests carry a `request_id` and expected answer type. IDs let concurrent agent output and nested tool activity appear under the correct work instead of becoming interleaved terminal text.

An `input_requested` event is presentation only; the workflow or runtime owns the waiting operation. An answer resumes that operation through its handler. Whether agents/tools may ask the user directly or must go through the orchestrator is still an open policy decision.

## Initial behavior

Only user-facing output is published: assistant replies, concise agent/tool activity, errors, and input requests. Internal prompts, credentials, and private model reasoning stay out of the UI stream. LLM-backed tools can report progress without exposing every generated token.

Delivery is bounded and applies backpressure. Events are not silently dropped. Session ordering describes delivery order, not a global execution order across modules.

Start with one local subscriber per session. The same command/event types can later be carried over JSON lines or HTTP without changing module responsibilities.

No frontend or network server is included in the Python prototype. The [headless application](orchestrator-module.md) dispatches these commands directly. Closing a subscription releases blocked publishers; use its context manager or call `await close()` on disconnect. Sessions have independent delivery queues. There is no event replay or multi-subscriber broadcast initially.

## Persistence

Save only the orchestrator conversation as chat history: user messages, completed orchestrator replies, and the orchestrator's own tool calls/results needed to continue that conversation. Reference task records for detailed execution results.

Agent/tool results, workflow progress, usage, and execution errors belong in the task database through the recording API. The exact additional recorder fields remain to be defined. Agent and tool conversations have no separate persistent chat store initially.

Streamed text fragments and live activity updates are temporary. After reconnecting, load the saved orchestrator conversation and current task records. The application interface does not persist or replay its entire event stream.
