import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from src.ariadne.infrastructure.container import DependencyRegistry

def update():
    # Use standard ticket tools
    tools = DependencyRegistry.get_work_item_tools()
    
    new_description = """### Epic: Multi-Agent Terminal User Interface (TUI) & Human-in-the-loop

**As an** Ariadne system user (developer/product manager),
**I want** a robust, terminal-based chat interface to interact with specialized lifecycle agents (Product Owner, Requirements, Engineer), manage configurations, and control agent actions,
**So that** I can seamlessly guide the software development process, securely provide credentials, and safely approve system modifications directly from my terminal.

#### **Acceptance Criteria**:
1. **Agent Management**:
   - Users can seamlessly switch between specialized agents using the `/agent [name]` command.
   - The UI clearly indicates the currently active agent.
2. **Command & Autocompletion System**:
   - A command bar is available with a dynamic suggestion dropdown.
   - Supports auto-completion for commands and their arguments using `Tab`.
   - Includes standard chat controls (`/clear`, `/quit`, `/help`, `/copy`).
3. **History & State Persistence**:
   - Users can manage agent-specific chat history using `/save`, `/load`, and `/clearhistory`.
   - Overall history status can be viewed using `/history`.
   - Conversations can be exported to and imported from JSON files via `/export` and `/import`.
4. **Secure Secret Management**:
   - Users can manage API keys and credentials securely using the `/secret` command (set, delete, and view masked status).
5. **Tool Execution & Safety Guardrails**:
   - The interface visually streams tool execution states (running, success, error) chronologically.
   - Suspended operations trigger an interactive **Approval Dialog** where the user can approve (`y`), deny (`n`), or allow for the rest of the session (`a`).
6. **Dynamic Settings**:
   - Users can inspect and modify runtime configurations and Pydantic-based settings dynamically using the `/settings` command.
7. **Rich User Experience**:
   - The interface features a scrollable conversation view with Markdown rendering for bot responses.
   - The chat input supports multi-line text (Ctrl+Enter for a new line, Enter to submit) and input history navigation (Up/Down arrows).
   - The `Escape` key gracefully aborts long-running agent operations.
8. **System/Agent State Visualization**:
   - Show the current state of the V-Model based on the agent that is running.
9. **Enhanced File/Diff Viewing**:
   - When an agent proposes code changes, present a side-by-side or inline syntax-highlighted diff view before the user approves a file write tool.
10. **Token Count Integration**:
    - Display current token usage/count to help manage context limits effectively.
"""
    ticket_id = '15'
    try:
        tools.system.update_description(ticket_id, new_description)
        print(f"Ticket {ticket_id} description updated successfully.")
    except Exception as e:
        print(f"Error updating ticket description: {e}")

if __name__ == "__main__":
    update()
