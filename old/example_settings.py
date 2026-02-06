"""Example showing dynamic Pydantic settings management."""

import asyncio
from typing import Literal
from enum import Enum
from pydantic import BaseModel, Field

from ariadne import ChatUI, BotResponse


class ModelProvider(str, Enum):
    """Available model providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LOCAL = "local"


class AppSettings(BaseModel):
    """Application settings - these will be editable via /settings command."""

    model_provider: ModelProvider = Field(
        default=ModelProvider.OPENAI,
        description="The AI model provider to use"
    )
    model_name: str = Field(
        default="gpt-4",
        description="Name of the model to use"
    )
    temperature: float = Field(
        default=0.7,
        description="Sampling temperature (0.0-2.0)"
    )
    max_tokens: int = Field(
        default=1000,
        description="Maximum tokens in response"
    )
    streaming: bool = Field(
        default=True,
        description="Enable streaming responses"
    )
    theme: Literal["dark", "light", "auto"] = Field(
        default="dark",
        description="UI color theme"
    )
    debug_mode: bool = Field(
        default=False,
        description="Enable debug logging"
    )

    class Config:
        # Allow changing values after creation
        validate_assignment = True


# Create settings instance
settings = AppSettings()

# Create UI with settings
ui = ChatUI(title="Settings Demo", settings=settings)


@ui.on_settings_change
def handle_settings_change(field: str, value) -> None:
    """Called when a setting is changed via /settings command."""
    print(f"Setting changed: {field} = {value}")


@ui.on_message
async def handle_message(message: str, response: BotResponse) -> None:
    """Handle messages showing current settings context."""
    response.thinking("Processing with current settings...")
    await asyncio.sleep(0.3)

    # Show current settings being used
    current = ui.get_settings()
    response.complete(
        f"**Message received:** {message}\n\n"
        f"**Current Settings:**\n"
        f"- Provider: {current.model_provider.value}\n"
        f"- Model: {current.model_name}\n"
        f"- Temperature: {current.temperature}\n"
        f"- Max tokens: {current.max_tokens}\n"
        f"- Streaming: {current.streaming}\n"
        f"- Theme: {current.theme}\n"
        f"- Debug: {current.debug_mode}\n\n"
        f"Use `/settings` to view and change these settings."
    )


if __name__ == "__main__":
    print("Settings Demo")
    print("=" * 40)
    print("Try these commands:")
    print("  /settings                    - View all settings")
    print("  /settings temperature        - View temperature setting")
    print("  /settings temperature 0.5    - Change temperature")
    print("  /settings model_provider     - View provider (shows choices)")
    print("  /settings streaming false    - Toggle streaming")
    print("  /settings theme light        - Change theme")
    print()
    ui.run()
