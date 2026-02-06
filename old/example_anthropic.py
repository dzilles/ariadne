"""Example integration with Anthropic API."""

from ariadne import ChatUI, BotResponse

# Requires: pip install anthropic
# Set ANTHROPIC_API_KEY environment variable

ui = ChatUI(title="Claude Chat")
ui.conversation.set_system_message("You are a helpful assistant.")


@ui.on_message
async def handle_message(message: str, response: BotResponse) -> None:
    """Handle messages using Anthropic API with streaming."""
    import anthropic

    client = anthropic.AsyncAnthropic()

    # Get conversation history in Anthropic format
    system, messages = ui.conversation.to_anthropic_messages()

    # Start streaming response
    response.start_response()

    async with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system or "",
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            response.append_response(text)

    response.complete()


@ui.on_message
async def handle_with_thinking(message: str, response: BotResponse) -> None:
    """Handle messages with extended thinking enabled."""
    import anthropic

    client = anthropic.AsyncAnthropic()
    system, messages = ui.conversation.to_anthropic_messages()

    # For extended thinking, we need to handle thinking blocks
    async with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=16000,
        thinking={
            "type": "enabled",
            "budget_tokens": 10000,
        },
        system=system or "",
        messages=messages,
    ) as stream:
        current_block_type = None

        async for event in stream:
            if event.type == "content_block_start":
                block = event.content_block
                if block.type == "thinking":
                    current_block_type = "thinking"
                    response.add_thinking("")
                elif block.type == "text":
                    current_block_type = "text"
                    response.start_response()

            elif event.type == "content_block_delta":
                delta = event.delta
                if current_block_type == "thinking" and hasattr(delta, "thinking"):
                    response.append_thinking(delta.thinking)
                elif current_block_type == "text" and hasattr(delta, "text"):
                    response.append_response(delta.text)

    response.complete()


if __name__ == "__main__":
    ui.run()
