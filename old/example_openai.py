"""Example integration with OpenAI API."""

from ariadne import ChatUI, BotResponse

# Requires: pip install openai
# Set OPENAI_API_KEY environment variable

ui = ChatUI(title="OpenAI Chat")
ui.conversation.set_system_message("You are a helpful assistant.")


@ui.on_message
async def handle_message(message: str, response: BotResponse) -> None:
    """Handle messages using OpenAI API with streaming."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI()

    # Get conversation history in OpenAI format
    messages = ui.conversation.to_openai_messages()

    # Start streaming response
    response.start_response()

    stream = await client.chat.completions.create(
        model="gpt-4",
        messages=messages,
        stream=True,
    )

    async for chunk in stream:
        if chunk.choices[0].delta.content:
            response.append_response(chunk.choices[0].delta.content)

    response.complete()


if __name__ == "__main__":
    ui.run()
