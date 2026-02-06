"""Example usage of the Ariadne chat UI."""

import asyncio
from ariadne import ChatUI, BotResponse


# Create the UI
ui = ChatUI(title="My Chatbot")


@ui.on_message
async def handle_message(message: str, response: BotResponse) -> None:
    """Handle incoming messages."""

    # Show thinking status (dynamic, gets replaced)
    response.thinking("Analyzing your message...")
    await asyncio.sleep(1)

    # Simulate a tool call
    if "file" in message.lower():
        response.tool("read_file", "reading example.txt...")
        await asyncio.sleep(0.5)

        # Tool succeeded, status will be cleared on complete()

    # Update thinking
    response.thinking("Formulating response...")
    await asyncio.sleep(0.5)

    # Complete with final response (clears status, shows green dot)
    response.complete(
        f"I received your message: **{message}**\n\n"
        "Here's a code example:\n\n"
        "```python\n"
        "print('Hello from Ariadne!')\n"
        "```\n\n"
        "Is there anything else I can help with?"
    )


if __name__ == "__main__":
    ui.run()
