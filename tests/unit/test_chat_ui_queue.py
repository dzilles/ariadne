import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.ui.app import ChatUI
from src.ariadne.ui.message import BotResponse, UserMessage
from src.ariadne.ui.widgets import ChatInput


def test_message_submitted_during_active_run_is_forwarded_to_busy_handler():
    async def scenario():
        ui = ChatUI()
        ui._focus_input = lambda: None
        started = asyncio.Event()
        release_first = asyncio.Event()
        handled = []
        busy = []

        @ui.on_message
        async def handler(message: str, response: BotResponse):
            handled.append(message)
            if message == "first":
                started.set()
                await release_first.wait()
            response.complete(f"done {message}")

        @ui.on_busy_message
        async def busy_handler(message: str, response: BotResponse):
            busy.append(message)
            response.info("Queued by controller.")

        await ui.on_chat_input_submitted(ChatInput.Submitted("first"))
        first_task = ui._current_task
        await started.wait()

        await ui.on_chat_input_submitted(ChatInput.Submitted("second"))

        assert isinstance(ui.conversation.messages[2], UserMessage)
        assert ui.conversation.messages[2].content == "second"
        assert ui.conversation.messages[3].response == "Queued by controller."

        release_first.set()
        await first_task

        assert handled == ["first"]
        assert busy == ["second"]
        assert ui._current_task is None

    asyncio.run(scenario())
