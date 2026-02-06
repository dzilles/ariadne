"""Example showing tool use with Anthropic API."""

import json
from ariadne import ChatUI, BotResponse

# Requires: pip install anthropic
# Set ANTHROPIC_API_KEY environment variable

ui = ChatUI(title="Claude with Tools")
ui.conversation.set_system_message("You are a helpful assistant with access to tools.")

# Define available tools
TOOLS = [
    {
        "name": "get_weather",
        "description": "Get the current weather for a location",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and state, e.g. San Francisco, CA",
                },
            },
            "required": ["location"],
        },
    },
    {
        "name": "calculate",
        "description": "Perform a mathematical calculation",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The math expression to evaluate",
                },
            },
            "required": ["expression"],
        },
    },
]


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool and return the result."""
    if name == "get_weather":
        # Simulated weather data
        return json.dumps({
            "location": args["location"],
            "temperature": "72°F",
            "conditions": "Sunny",
        })
    elif name == "calculate":
        try:
            result = eval(args["expression"])  # Note: Use a safe evaluator in production
            return str(result)
        except Exception as e:
            return f"Error: {e}"
    return "Unknown tool"


@ui.on_message
async def handle_message(message: str, response: BotResponse) -> None:
    """Handle messages with tool use."""
    import anthropic

    client = anthropic.AsyncAnthropic()
    system, messages = ui.conversation.to_anthropic_messages()

    # Initial request
    result = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system or "",
        messages=messages,
        tools=TOOLS,
    )

    # Process response, handling tool use
    while result.stop_reason == "tool_use":
        # Find tool use blocks
        tool_results = []
        for block in result.content:
            if block.type == "tool_use":
                # Show tool call in UI
                response.add_tool_call(block.name, block.input)

                # Execute the tool
                tool_result = execute_tool(block.name, block.input)
                response.update_tool_result(tool_result)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": tool_result,
                })

        # Continue conversation with tool results
        messages.append({"role": "assistant", "content": result.content})
        messages.append({"role": "user", "content": tool_results})

        result = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system or "",
            messages=messages,
            tools=TOOLS,
        )

    # Extract final text response
    for block in result.content:
        if hasattr(block, "text"):
            response.complete(block.text)
            return

    response.complete("(No response)")


if __name__ == "__main__":
    ui.run()
