import asyncio
import copy
import inspect
import os
from typing import Protocol

from ariadne._util import text, integer
from ariadne.errors import Error
from .model import Binding, Request, Response, Cancellation


async def deliver(callback, value):
    result = callback(value)
    if inspect.isawaitable(result):
        await result


class CredentialResolver(Protocol):
    def resolve(self, reference: str) -> str: ...


class EnvironmentCredentials:
    def resolve(self, reference):
        from ariadne.configuration.validation import variable
        if not isinstance(reference, str) or not reference.startswith("env:") or not variable(reference[4:]):
            raise Error.invalid("Unsupported credential reference; use env:NAME")
        key = os.environ.get(reference[4:])
        if not key or any(ord(c) < 32 or ord(c) == 127 for c in key):
            raise Error("AUTHENTICATION_ERROR", f"Set environment variable {reference[4:]}")
        return key


class Adapter(Protocol):
    async def generate(self, binding: Binding, request: Request, credentials: CredentialResolver,
                       cancellation: Cancellation, emit) -> Response: ...


class Gateway:
    """Shared adapters; each invocation keeps its own request and conversation state."""

    def __init__(self, credentials=None):
        from .openrouter import OpenRouter
        self.credentials = credentials or EnvironmentCredentials()
        self.adapters = {"openrouter": OpenRouter()}

    def register_adapter(self, kind, adapter):
        text(kind, "adapter kind")
        self.adapters[kind] = adapter

    async def generate(self, binding, request, context, cancellation=None, emit=lambda event: None):
        cancellation = cancellation or Cancellation()
        # Capture caller-owned values before the first await so a concurrent edit
        # cannot change an invocation's model, input, or correlation fields.
        binding, request, context = copy.deepcopy(binding), copy.deepcopy(request), copy.deepcopy(context)

        async def forward(event):
            await deliver(emit, {"context": context.to_dict(), **event})

        await forward({"type": "started"})
        try:
            cancellation.check()
            binding.provider.validate()
            text(binding.model, "model ID")
            text(context.call_id, "call ID")
            text(context.caller_id, "caller ID")
            integer(binding.timeout_ms, "timeout_ms", 1)
            if context.snapshot_id != binding.snapshot_id or not request.messages:
                raise Error.invalid("Request needs messages and matching configuration snapshot IDs")
            adapter = self.adapters.get(binding.provider.adapter)
            if adapter is None:
                raise Error("UNSUPPORTED_ADAPTER", "No adapter registered for this connection")

            async def incremental(event):
                if event.get("type") not in ("text_delta", "usage", "tool_call_ready"):
                    raise Error("ADAPTER_ERROR", "Adapter emitted an invalid lifecycle event")
                await forward(event)

            response = await adapter.generate(binding, request, self.credentials, cancellation, incremental)
            cancellation.check()
            if not isinstance(response, Response):
                raise Error("ADAPTER_ERROR", "Adapter returned an invalid response")
        except asyncio.CancelledError:
            cancellation.cancel()
            await forward({"type": "failed", "error": Error("CANCELLED", "Model request cancelled").to_dict()})
            raise
        except Error as exc:
            await forward({"type": "failed", "error": exc.to_dict()})
            raise
        except Exception as exc:
            error = Error("ADAPTER_ERROR", "Model adapter failed unexpectedly")
            await forward({"type": "failed", "error": error.to_dict()})
            raise error from exc
        await forward({"type": "finished", "response": response.to_dict()})
        return response
