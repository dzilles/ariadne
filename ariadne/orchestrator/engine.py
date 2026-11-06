from __future__ import annotations

import asyncio
import copy
from pathlib import Path

from ariadne._util import new_id, text, loads
from ariadne.errors import Error
from ariadne.interaction import Source, EventContext
from ariadne.llm import Binding, CallContext, Cancellation, Message, Request
from ariadne.task import TaskStore, DemoEmbedder
from .model import Entry, State
from .store import ConversationStore, close_pending
from .tools import TaskTools


async def notify(interface, session_id, source, context, payload):
    try:
        await interface.publish(session_id, source, context, payload)
    except Error as exc:
        if exc.code not in ("NO_SUBSCRIBER", "DISCONNECTED"):
            raise


class Orchestrator:
    def __init__(self, configuration, conversation_path, task_path):
        self.configuration, self.conversation_path, self.task_path = configuration, Path(conversation_path), Path(task_path)

    async def turn(self, session_id, command_id, message, gateway, interface, cancellation=None):
        cancellation = cancellation or Cancellation()
        context = EventContext(command_id, command_id)
        source = Source("orchestrator", "orchestrator")
        error, externally_cancelled = None, False
        try:
            with ConversationStore(self.conversation_path) as store:
                conversation = store.get(session_id)
                if conversation.state == State.RUNNING:
                    raise Error("BUSY", "This conversation already has an active turn")
                text(message, "message")
                if len(message.encode("utf-8")) > 65536:
                    raise Error.invalid("Message exceeds 65536 bytes")
                conversation.state, conversation.active_run_id, conversation.last_error = State.RUNNING, command_id, None
                if not any(e.message.role == "user" for e in conversation.entries):
                    conversation.title = message[:60]
                conversation.entries.append(Entry(new_id("message"), Message.text("user", message)))
                store.save(conversation)
                try:
                    await self._run_turn(store, conversation, gateway, interface, context, cancellation)
                except asyncio.CancelledError:
                    cancellation.cancel()
                    error, externally_cancelled = Error("CANCELLED", "Orchestrator turn cancelled"), True
                except Error as exc:
                    error = exc
                except Exception as exc:
                    error = Error("EXECUTION_ERROR", "Orchestrator turn failed unexpectedly")
                conversation.active_run_id = None
                if error:
                    close_pending(conversation, error.code, "The turn stopped. Tool execution may have occurred; inspect task records before retrying.")
                    conversation.state, conversation.last_error = State.FAILED, error.to_dict()
                else:
                    conversation.state = State.IDLE
                store.save(conversation)
        except Error as exc:
            error = exc
        if error:
            await notify(interface, session_id, source, context, {"type": "error", "error": error.to_dict()})
        outcome = "cancelled" if error and error.code == "CANCELLED" else "failed" if error else "completed"
        await notify(interface, session_id, source, context, {"type": "run_finished", "outcome": outcome})
        if externally_cancelled:
            raise asyncio.CancelledError
        if error:
            raise error

    async def _run_turn(self, store, conversation, gateway, interface, event_context, cancellation):
        snapshot = self.configuration.get_snapshot(conversation.snapshot_id)
        binding = Binding.from_snapshot(snapshot, conversation.profile_id)
        definitions = TaskTools.definitions(snapshot.configuration, conversation.profile_id)
        limit = min(100, snapshot.configuration.profiles[conversation.profile_id].settings.get("max_tool_calls", 12))
        source, used = Source("orchestrator", conversation.profile_id), 0
        with TaskStore(self.task_path) as tasks:
            tasks.register_embedding_model(DemoEmbedder().model())
            tools = TaskTools(tasks, snapshot.configuration, conversation.project_id, conversation.profile_id)
            for _ in range(limit + 1):
                cancellation.check()
                call_id, message_id = new_id("call"), new_id("message")
                context = copy.deepcopy(event_context)
                context.call_id = call_id

                async def publish(payload):
                    await notify(interface, conversation.id, source, context, payload)

                await publish({"type": "message_started", "message_id": message_id})

                async def emit(event):
                    if event["type"] == "text_delta":
                        await publish({"type": "message_delta", "message_id": message_id, "text": event["text"]})

                request = Request([copy.deepcopy(e.message) for e in conversation.entries], definitions)
                call_context = CallContext(call_id, conversation.profile_id, snapshot.id, conversation.id, event_context.run_id)
                response = await gateway.generate(binding, request, call_context, cancellation, emit)
                if response.finish_reason not in ("stop", "tool_calls"):
                    raise Error("INCOMPLETE_RESPONSE", f"Model stopped with {response.finish_reason}")
                calls, reply = response.message.tool_calls, response.message.content or ""
                if not calls and not reply.strip():
                    raise Error("EMPTY_RESPONSE", "Model returned no reply")
                previous = {c.id for e in conversation.entries for c in e.message.tool_calls}
                if len({c.id for c in calls}) != len(calls) or any(c.id in previous for c in calls):
                    raise Error("PROTOCOL_ERROR", "Model reused a tool-call ID")
                conversation.entries.append(Entry(message_id, response.message, call_id, response.usage))
                # Journal requests before any task write; never replay ambiguous calls.
                store.save(conversation)
                await publish({"type": "message_finished", "message_id": message_id, "text": reply})
                if not calls:
                    return
                for call in calls:
                    cancellation.check()
                    if used >= limit:
                        raise Error("TOOL_LIMIT", "Orchestrator tool-call limit reached")
                    used += 1
                    await publish({"type": "activity_updated", "label": call.name, "state": "running"})
                    try:
                        result = {"ok": True, "result": tools.call(call.name, loads(call.arguments))}
                    except Error as exc:
                        result = {"ok": False, "error": exc.to_dict()}
                    conversation.entries.append(Entry(new_id("message"), Message.tool(call.id, result)))
                    store.save(conversation)
                    await publish({"type": "activity_updated", "label": call.name, "state": "completed" if result["ok"] else "failed"})
        raise Error("TOOL_LIMIT", "Orchestrator round limit reached")
