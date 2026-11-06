# LLM access module

[Main architecture](../architecture.md)

Implemented in [`ariadne/llm/`](../../ariadne/llm/__init__.py), with tests in `tests/llm/`. Provides model access for the orchestrator, agents, context service, and future tools containing LLMs. OpenRouter is the first adapter; other adapters use the same interface.

## Responsibilities

The configuration module stores the API connection, model, and generation settings. This module resolves credentials at runtime, performs API requests, and translates responses, streaming output, usage, and errors into common types.

Each caller owns its prompts, conversation history, and tool loop. The LLM module returns requested tool calls; application code validates and executes them. Concurrent calls have separate request state. No conversation is implicitly shared between callers.

The orchestrator persists its conversation. Agent/tool execution information is recorded in the task database by runtime and workflow code; their model conversations remain in memory initially. The LLM module provides no conversation storage.

## Configuration

The configuration module stores:

| Record | Fields |
| --- | --- |
| API connection | `id`, `adapter` (initially `openrouter`), `base_url`, `credential_ref` |
| Component profile | `provider_id` referencing an API connection; `model` identifies the model on that connection. |

API connections are stored in the `providers` map. Different components can share a connection while choosing different models. A future LLM-backed tool can have its own profile using component `tool`.

```json
{
  "providers": {
    "openrouter": {
      "id": "openrouter",
      "adapter": "openrouter",
      "base_url": "https://openrouter.ai/api/v1",
      "credential_ref": "env:OPENROUTER_API_KEY"
    }
  },
  "profiles": {
    "orchestrator": {
      "id": "orchestrator",
      "component": "orchestrator",
      "provider_id": "openrouter",
      "model": "<chosen OpenRouter model ID>",
      "prompt_ids": ["orchestrator"]
    }
  }
}
```

This fragment illustrates the connection fields; its prompt must also exist. Older configurations and snapshots remain readable, but executing an older profile requires an explicit connection and `provider_id`. Save credentials on the connection and remove the profile's legacy `credential_ref`. Run snapshots include connection settings and references, never resolved keys.

## Interface

| Operation | Purpose |
| --- | --- |
| `await gateway.generate(binding, request, context, cancellation=None, emit=callback)` | Deliver common LLM events to a callback during one model invocation, then return the complete response or an error. |
| `register_adapter(kind, adapter)` | Application setup registers an implementation, initially OpenRouter. |

`Binding.from_snapshot(snapshot, profile_id)` resolves the connection, model, and generation settings. `request` contains text messages and optional function-tool schemas. Prompt rendering happens before this call. Tool permissions and workflow limits belong to the caller. The API is asynchronous; event callbacks may be synchronous or asynchronous. Each call has its own request and cancellation state.

`context` contains a unique `call_id`, `caller_id`, and `snapshot_id`, with optional `session_id`, `run_id`, `task_id`, and `parent_call_id`. A tool's nested LLM invocation can reference its parent call. A call without a task remains valid.

Events include `started`, `text_delta`, `tool_call_ready`, `usage`, and one terminal `finished` or `failed`. Successful completion includes the full assistant message and stop reason. Tool arguments become usable only when complete and validated. Preserve provider continuation data needed for subsequent messages, such as reasoning metadata, without displaying it as chat text.

Usage retains reported input/output tokens and optional cost; missing measurements remain unknown. Errors distinguish authentication, payment, rate limiting, timeout, cancellation, protocol errors, and provider failure. Partial streams produce failure. There are no automatic retries or model fallbacks; OpenRouter provider fallbacks are also disabled for this prototype.

## OpenRouter first

Use `POST /api/v1/chat/completions`, with streaming and function tools. Translate OpenRouter's SSE framing, including keep-alive comments and mid-stream errors, inside the adapter. Models must support the requested features; do not silently discard tool schemas or other required parameters. See the official [API reference](https://openrouter.ai/docs/api_reference/overview), [streaming guide](https://openrouter.ai/docs/api_reference/streaming), and [tool-calling guide](https://openrouter.ai/docs/guides/features/tool-calling).

The default transport uses Python’s native HTTP/HTTPS client on a daemon I/O thread, delivering bytes through a bounded asynchronous queue. Cancellation closes the active socket; an overall deadline bounds the call. No subprocess is required. `HttpTransport` can be replaced independently of the adapter. Supported profile settings are `max_output_tokens` (default 2048), `temperature`, `top_p`, and `timeout_ms` (default 120000). OpenRouter routing requires support for the requested parameters. Multimodal input and structured-output configuration are future extensions.

The module returns events to its caller. The caller decides what to forward to the [application interface](interaction-module.md) and which measurements to record through the task recording API. The LLM module has no task-write or terminal-output dependency.
