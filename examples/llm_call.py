"""A live API example: uses your configured model and OPENROUTER_API_KEY."""
import asyncio
import sys

from ariadne._util import new_id
from ariadne.configuration import ConfigurationStore
from ariadne.llm import Gateway, Binding, CallContext, Request, Message


async def main():
    root = sys.argv[1] if len(sys.argv) > 1 else ".ariadne"
    profile = sys.argv[2] if len(sys.argv) > 2 else "orchestrator"
    snapshot = ConfigurationStore(root).create_snapshot()
    binding = Binding.from_snapshot(snapshot, profile)
    context = CallContext(new_id("call"), "llm-example", snapshot.id)
    def emit(event):
        if event["type"] == "text_delta":
            print(event["text"], end="", flush=True)
    await Gateway().generate(binding, Request([Message.text("user", "Say hello in one sentence.")]), context, emit=emit)
    print()


if __name__ == "__main__":
    asyncio.run(main())
