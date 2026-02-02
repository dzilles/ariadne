import os
import sys
import json
import logging
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import WordCompleter

# Ensure src module can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.po_agent import ProductOwnerAgent
from src.agents.engineer_agent import EngineerAgent
from src.agents.requirements_agent import RequirementsAgent
from src.configuration.logging_config import setup_logging

# Agent Registry: Name -> Class
AGENT_REGISTRY = {
    "PO": ProductOwnerAgent,
    "Requirements": RequirementsAgent,
    "Engineer": EngineerAgent,
}

def get_history_filename(agent_name):
    return f".chat_history_{agent_name}.json"

def configure_logging():
    """Silences verbose loggers to ensure a clean chat interface."""
    loggers_to_silence = [
        "httpx",
        "httpcore",
        "google",
        "google_genai._api_client", # Silence Google GenAI retry logs
        "urllib3",
        "src.configuration.llm_factory",  # Silence LLM factory logs
        "src.configuration.config"
    ]
    for logger_name in loggers_to_silence:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

def save_chat_history(agent, agent_name):
    """Saves the current agent's history to a JSON file."""
    filename = get_history_filename(agent_name)
    try:
        if hasattr(agent, 'get_history'):
            history = agent.get_history()
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2)
            print(f"[Chat history saved to {filename}]")
        else:
            print("[Error: Agent does not support saving history]")
    except Exception as e:
        print(f"[Error saving history: {e}]")

def load_chat_history(agent, agent_name):
    """Loads chat history from a JSON file if it exists and prints it."""
    filename = get_history_filename(agent_name)
    if not os.path.exists(filename):
        return

    print(f"\nFound saved chat history for {agent_name} ({filename}).")
    choice = input("Do you want to load it? (y/n): ").strip().lower()
    if choice != 'y':
        return

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            history = json.load(f)
        
        if hasattr(agent, 'load_history'):
            agent.load_history(history)
            print("[Chat history loaded]")
            
            # Print the restored history
            print("\n--- Restored History ---")
            for msg in history:
                msg_type = msg.get('type')
                content = msg.get('content')
                
                if msg_type == 'human':
                    print(f"\nYou: {content}")
                elif msg_type == 'ai':
                    # Handle potential list content in AI messages
                    if isinstance(content, list):
                        text_parts = []
                        for part in content:
                            if isinstance(part, str): text_parts.append(part)
                            elif isinstance(part, dict) and 'text' in part: text_parts.append(part['text'])
                        content = "".join(text_parts)
                    
                    if content:
                        print(f"{agent_name}: {content}")
                    
                    # If there are tool calls (in tool_calls field), usually content is empty or partial
                    # We might want to show tool calls if stored, but let's stick to text content for now.
            print("------------------------\n")
            
        else:
            print("[Error: Agent does not support loading history]")
    except Exception as e:
        print(f"[Error loading history: {e}]")

def switch_agent(current_agent_name):
    print("\nAvailable Agents:")
    for name in AGENT_REGISTRY.keys():
        prefix = "*" if name == current_agent_name else " "
        print(f" {prefix} {name}")
    
    session = PromptSession()
    while True:
        selection = session.prompt(HTML("<b>Select Agent (type name):</b> ")).strip()
        
        # Allow case-insensitive matching
        matched_name = next((name for name in AGENT_REGISTRY if name.lower() == selection.lower()), None)
        
        if matched_name:
            if matched_name == current_agent_name:
                print(f"Already chatting with {matched_name}.")
                return None, None # No change
            
            try:
                print(f"Initializing {matched_name} Agent...")
                new_agent = AGENT_REGISTRY[matched_name]()
                print(f"Switched to {matched_name} Agent. History cleared.")
                
                # Load history for the new agent
                load_chat_history(new_agent, matched_name)
                
                return matched_name, new_agent
            except Exception as e:
                print(f"Error initializing {matched_name}: {e}")
                return None, None
        
        print("Invalid selection. Please type one of the names listed above (or Ctrl+C to cancel).")

def main():
    # Initialize central logging
    setup_logging()
    
    # Configure logging before doing anything else
    configure_logging()
    
    print("Initializing Ariadne Chat Interface...")
    print("--------------------------------------")
    
    current_agent_name = "PO"
    
    try:
        agent = ProductOwnerAgent()
        print(f"{current_agent_name} Agent is ready.")
        
        # Check for saved history for the initial agent
        load_chat_history(agent, current_agent_name)
        
        print("Commands:")
        print("  /agent  - Switch agent")
        print("  /save   - Save chat history")
        print("  /clear  - Reset history")
        print("  /exit   - Quit\n")
        print("Tip: Use Up/Down arrows for command history.")
    except Exception as e:
        print(f"Error initializing agent: {e}")
        return

    # Command completer
    command_completer = WordCompleter(['/agent', '/save', '/clear', '/exit'], ignore_case=True)

    # Initialize Prompt Toolkit Session with History and Completer
    session = PromptSession(history=InMemoryHistory(), completer=command_completer)

    # Style for the prompt
    style = Style.from_dict({
        'agent': '#00aa00 bold',
        'you': '#00aaaa',
    })

    while True:
        try:
            # Standard single-line prompt
            prompt_text = HTML(f"<agent>{current_agent_name}</agent>> <you>You</you>: ")
            user_input = session.prompt(prompt_text, style=style).strip()
            
            if not user_input:
                continue
                
            if user_input.lower() == "/exit":
                print("Goodbye!")
                break
                
            if user_input.lower() == "/save":
                save_chat_history(agent, current_agent_name)
                continue
                
            if user_input.lower() == "/clear":
                agent.clear_history()
                print("[Chat history cleared]")
                continue
            
            if user_input.lower() == "/agent":
                new_name, new_agent = switch_agent(current_agent_name)
                if new_agent:
                    current_agent_name = new_name
                    agent = new_agent
                continue
            
            # Send to agent
            print(f"\n{current_agent_name} is thinking...")
            response = agent.chat(user_input)
            print(f"\n{current_agent_name}: {response}\n")
            
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
            continue
        except Exception as e:
            print(f"\nError: {e}\n")

if __name__ == "__main__":
    main()