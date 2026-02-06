"""Advanced example showing error handling and tool failures."""

import asyncio
from ariadne import ChatUI, BotResponse


ui = ChatUI(title="Advanced Chatbot")


@ui.on_message
async def handle_message(message: str, response: BotResponse) -> None:
    """Handle messages with different scenarios."""

    message_lower = message.lower()

    # Simulate an error
    if "error" in message_lower:
        response.thinking("Processing request...")
        await asyncio.sleep(0.5)
        response.error("Something went wrong! This is a simulated error.")
        return

    # Simulate a failed tool call (persists)
    if "fail" in message_lower:
        response.thinking("Attempting operation...")
        await asyncio.sleep(0.5)

        response.tool("delete_file", "/etc/passwd")
        await asyncio.sleep(0.5)

        # Tool failed - this will persist
        response.tool_error("delete_file", "Permission denied")

        response.complete("I couldn't complete the operation due to the error above.")
        return

    # Simulate multiple tool calls (only failures persist)
    if "search" in message_lower:
        response.thinking("I'll search for relevant information...")
        await asyncio.sleep(0.5)

        response.tool("web_search", f'searching for "{message}"...')
        await asyncio.sleep(1)

        response.tool("read_page", "fetching https://example.com...")
        await asyncio.sleep(0.5)

        # All succeeded, status cleared on complete
        response.complete(
            "Based on my search, here's what I found:\n\n"
            "1. First result summary\n"
            "2. Second result summary\n"
            "3. Third result summary\n\n"
            "Would you like more details on any of these?"
        )
        return

    # Simulate streaming response
    if "stream" in message_lower:
        response.thinking("Generating response...")
        await asyncio.sleep(0.5)

        response.start_response()
        words = "This is a streaming response that appears word by word.".split()
        for word in words:
            response.append_response(word + " ")
            await asyncio.sleep(0.1)

        response.complete()
        return

    # Simulate markdown response
    if "markdown" in message_lower:
        response.thinking("Generating markdown example...")
        await asyncio.sleep(0.5)

        response.complete(
            "# Markdown Example\n\n"
            "This is a **bold** and *italic* text demo.\n\n"
            "## Code Blocks\n\n"
            "Inline `code` looks like this.\n\n"
            "```python\n"
            "def hello(name: str) -> str:\n"
            "    return f'Hello, {name}!'\n"
            "\n"
            "print(hello('World'))\n"
            "```\n\n"
            "## Lists\n\n"
            "Unordered:\n"
            "- First item\n"
            "- Second item\n"
            "- Third item\n\n"
            "Ordered:\n"
            "1. Step one\n"
            "2. Step two\n"
            "3. Step three\n\n"
            "## Table\n\n"
            "| Feature | Status |\n"
            "|---------|--------|\n"
            "| Bold | ✓ |\n"
            "| Italic | ✓ |\n"
            "| Code | ✓ |\n\n"
            "## Blockquote\n\n"
            "> This is a blockquote.\n"
            "> It can span multiple lines.\n\n"
            "---\n\n"
            "That's the markdown demo!"
        )
        return

    # Default response
    response.thinking("Processing your request...")
    await asyncio.sleep(0.5)

    response.complete(
        f"You said: *{message}*\n\n"
        "Try these commands:\n"
        "- Say **error** to see an error response\n"
        "- Say **fail** to see a persistent tool failure\n"
        "- Say **search** to see tool calls that succeed\n"
        "- Say **stream** to see a streaming response\n"
        "- Say **markdown** to see markdown rendering\n"
        "- Type `/` to see available commands"
    )


if __name__ == "__main__":
    ui.run()
