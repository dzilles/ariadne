import os
import sys
import json
import logging
import asyncio

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, Input, Static, Button, ListView, ListItem, Label, Markdown
from textual.reactive import reactive
from textual.message import Message
from textual import work
from textual.binding import Binding

# Ensure src module can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.po_agent import ProductOwnerAgent
from src.agents.engineer_agent import EngineerAgent
from src.agents.requirements_agent import RequirementsAgent
from src.configuration.logging_config import setup_logging

# Configure logging to file only
logging.basicConfig(level=logging.INFO, filename="ariadne_tui.log", filemode="w")

AGENT_REGISTRY = {
    "Product Owner": ProductOwnerAgent,
    "Requirements": RequirementsAgent,
    "Engineer": EngineerAgent,
}

def get_history_filename(agent_name):
    name_map = {
        "Product Owner": "PO",
        "Requirements": "Requirements",
        "Engineer": "Engineer"
    }
    safe_name = name_map.get(agent_name, agent_name)
    return f".chat_history_{safe_name}.json"

class ChatMessage(Static):
    """A widget to display a chat message."""
    
    def __init__(self, sender: str, text: str, is_user: bool = False):
        super().__init__()
        self.sender = sender
        self.text = text
        self.is_user = is_user
        
    def compose(self) -> ComposeResult:
        role_class = "user-message" if self.is_user else "agent-message"
        yield Label(f"{self.sender}:", classes=f"message-sender {role_class}-header")
        yield Markdown(self.text, classes=f"message-content {role_class}-content")

class AgentList(ListView):
    """Sidebar widget to select agents."""
    pass

class AriadneApp(App):
    """The Ariadne TUI Application."""
    
    CSS = """
    Screen {
        layout: horizontal;
    }

    #sidebar {
        width: 30;
        dock: left;
        background: $panel;
        border-right: vkey $accent;
    }

    #sidebar-header {
        text-align: center;
        background: $accent;
        color: $text;
        padding: 1;
        text-style: bold;
    }

    #chat-area {
        width: 1fr;
        height: 1fr;
        layout: vertical;
    }

    #chat-scroll {
        width: 1fr;
        height: 1fr;
        border: solid $secondary;
        padding: 1;
        background: $surface; 
    }

    #input-area {
        height: auto;
        min-height: 3;
        border-top: solid $secondary;
        padding: 1;
    }

    ChatMessage {
        margin-bottom: 1;
        height: auto;
    }

    .message-sender {
        text-style: bold;
    }

    .user-message-header {
        color: $success;
    }

    .agent-message-header {
        color: $primary;
    }

    .message-content {
        padding-left: 2;
    }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+s", "save_history", "Save History"),
        ("ctrl+l", "clear_history", "Clear History"),
    ]

    current_agent_name = reactive("Product Owner")

    def __init__(self):
        super().__init__()
        self.agents = {} 
        self.current_agent = None

    def compose(self) -> ComposeResult:
        yield Header()
        
        with Container(id="sidebar"):
            yield Label("AGENTS", id="sidebar-header")
            yield AgentList(
                *[
                    ListItem(Label(name), name=name)
                    for name in AGENT_REGISTRY.keys()
                ],
                id="agent-list"
            )

        with Container(id="chat-area"):
            # Use VerticalScroll for the chat history
            yield VerticalScroll(id="chat-scroll")
            
            # Input area stays at the bottom due to vertical layout
            with Container(id="input-area"):
                yield Input(placeholder="Type a message... (or /save, /clear, /exit)", id="chat-input")
        
        yield Footer()

    def on_mount(self):
        self.query_one("#agent-list").index = 0
        self.switch_agent("Product Owner")
        self.title = "Ariadne CLI"

    def on_list_view_selected(self, event: ListView.Selected):
        if event.item:
            agent_name = event.item.name
            if agent_name != self.current_agent_name:
                self.switch_agent(agent_name)

    async def on_input_submitted(self, event: Input.Submitted):
        user_input = event.value.strip()
        if not user_input:
            return

        event.input.value = ""

        if user_input.lower() in ["/exit", "/quit"]:
            self.exit()
            return
        if user_input.lower() == "/save":
            self.action_save_history()
            return
        if user_input.lower() == "/clear":
            self.action_clear_history()
            return

        # Display User Message
        self.post_message_to_ui("You", user_input, is_user=True)

        # Process with Agent
        self.process_chat(user_input)

    @work(exclusive=True, thread=True)
    def process_chat(self, user_input: str):
        if not self.current_agent:
            self.notify("Agent not initialized!", severity="error")
            return

        try:
            response = self.current_agent.chat(user_input)
            # Update UI from the main thread
            self.call_from_thread(self.post_message_to_ui, self.current_agent_name, response, False)
        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")

    def post_message_to_ui(self, sender: str, text: str, is_user: bool):
        """Mounts a message widget to the scroll container. Safe to call from main thread."""
        scroll = self.query_one("#chat-scroll")
        scroll.mount(ChatMessage(sender, text, is_user))
        scroll.scroll_end(animate=False)

    def switch_agent(self, agent_name: str):
        self.current_agent_name = agent_name
        
        scroll = self.query_one("#chat-scroll")
        scroll.remove_children()

        if agent_name not in self.agents:
            try:
                self.notify(f"Initializing {agent_name}...", title="System")
                agent_class = AGENT_REGISTRY[agent_name]
                self.agents[agent_name] = agent_class()
                self.load_history_for_agent(agent_name, self.agents[agent_name])
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                logging.error(f"Failed to load {agent_name}:\n{tb}")
                self.notify(f"Failed to load {agent_name}: [{type(e).__name__}] {e}", severity="error")
                return

        self.current_agent = self.agents[agent_name]
        self.sub_title = f"Chatting with {agent_name}"
        self.query_one("#chat-input").focus()
        
        self.repopulate_chat(self.current_agent)

    def load_history_for_agent(self, agent_name, agent):
        filename = get_history_filename(agent_name)
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                if hasattr(agent, 'load_history'):
                    agent.load_history(history)
            except Exception as e:
                logging.error(f"Error loading history: {e}")

    def repopulate_chat(self, agent):
        if not hasattr(agent, 'chat_history'):
            return

        for msg in agent.chat_history:
            if hasattr(msg, 'type'):
                msg_type = msg.type
                content = msg.content
                
                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, str): text_parts.append(part)
                        elif isinstance(part, dict) and 'text' in part: text_parts.append(part['text'])
                    content = "".join(text_parts)

                if msg_type == 'human':
                    self.post_message_to_ui("You", content, True)
                elif msg_type == 'ai':
                    self.post_message_to_ui(self.current_agent_name, content, False)

    def action_save_history(self):
        if not self.current_agent:
            return
        
        filename = get_history_filename(self.current_agent_name)
        try:
            if hasattr(self.current_agent, 'get_history'):
                history = self.current_agent.get_history()
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(history, f, indent=2)
                self.notify(f"History saved to {filename}")
        except Exception as e:
            self.notify(f"Error saving history: {e}", severity="error")

    def action_clear_history(self):
        if hasattr(self.current_agent, 'clear_history'):
            self.current_agent.clear_history()
            self.query_one("#chat-scroll").remove_children()
            self.notify("History cleared")

def main():
    app = AriadneApp()
    app.run()

if __name__ == "__main__":
    main()
