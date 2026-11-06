"""Shared asynchronous model access. Callers own prompts, history, and tool loops."""
from .model import (Binding, Cancellation, CallContext, Role, ToolCall, Message, ToolDefinition,
                    Request, Usage, Response)
from .gateway import Gateway, Adapter, CredentialResolver, EnvironmentCredentials
from .openrouter import OpenRouter
from .transport import NativeHttpTransport, HttpTransport, HttpRequest, Headers, Data

__all__ = [name for name in globals() if not name.startswith("_")]
