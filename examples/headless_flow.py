"""Run a real orchestrator/tool loop with a deterministic offline model adapter."""
import asyncio
from pathlib import Path
import tempfile

from ariadne._util import dumps
from ariadne.llm import Gateway, Message, Response, ToolCall
from ariadne.orchestrator import Application, Options, initialize


class OfflineModel:
    async def generate(self, binding, request, credentials, cancellation, emit):
        cancellation.check()
        if request.messages[-1].role != "tool":
            call = ToolCall("example-create-task", "create_task", dumps({"description": "Implement Android chat streaming", "tags": ["android", "streaming"]}))
            return Response(Message("assistant", tool_calls=[call]), "tool_calls")
        answer = "Created a draft task for Android chat streaming."
        await emit({"type": "text_delta", "text": answer})
        return Response(Message.text("assistant", answer), "stop")


async def run():
    with tempfile.TemporaryDirectory(prefix="ariadne-headless-") as directory:
        root = Path(directory)
        initialize(root, "example/offline-model")
        gateway = Gateway()
        gateway.register_adapter("openrouter", OfflineModel())
        async with await Application.start(Options(root, root / "tasks.sqlite", "android-demo"), gateway) as app:
            conversation = app.create_conversation()
            async with app.interface.subscribe(conversation.id) as events:
                app.submit(conversation.id, {"type": "send_message", "text": "Create a task for Android chat streaming"})
                async for event in events:
                    print(dumps(event))
                    if event.payload["type"] == "run_finished":
                        break
            print(dumps({"tasks": app.tasks(), "saved_messages": len(app.conversation(conversation.id).entries)}, pretty=True))


if __name__ == "__main__":
    asyncio.run(run())
