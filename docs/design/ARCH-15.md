# ARCH-15: Terminal User Interface & Human-in-the-loop

**Traceability:**
- **Originating Ticket:** #15
- **Refinement Tickets:** #19
- **Requirement Link:** [PENDING LINK]

## 1. Overview
This architecture defines the Terminal User Interface (TUI) and Human-in-the-loop (HITL) mechanism for the autonomous agent system. The TUI provides real-time monitoring, multi-agent control, and a command interface. The HITL mechanism ensures that sensitive tool calls are intercepted and approved by the user before execution. A key focus of this architecture is testability, enabling automated UI testing and headless execution.

## 2. Component Design / Data Models

### 2.1 TUI Components (Textual)
All interactive components MUST have unique, stable `id` attributes (FR-14).

- **ChatUI (App):** The root application container. Manages global state, message routing, and the event loop.
    - `id`: `chat-app`
    - **Testability Hooks:**
        - `get_state()`: Returns a dictionary of the current UI state (active agent, modal status, etc.). (FR-13)
        - `simulate_keypress(key)`: Triggers key events programmatically. (FR-15)
        - `simulate_input(text)`: Injects text into the input buffer. (FR-15)
- **ConversationView (ScrollableContainer):** Displays message history.
    - `id`: `conversation-view`
- **BotResponseWidget (Static):** Represents an agent response turn.
    - Contains `StatusWidget` instances for tool calls.
- **StatusWidget (Static):** Visual indicator for tool execution.
- **ApprovalDialog (Container):** Modal overlay for HITL.
    - `id`: `approval-dialog`
    - Buttons: `approve-btn`, `deny-btn`, `allow-session-btn`.
- **ChatInput (Container):**
    - `id`: `chat-input-container`
    - `ChatTextArea` (id: `chat-input-text`)

### 2.2 Data Models
- **Conversation:** Collection of `UserMessage` and `BotResponse` objects.
- **BotResponse:** State machine for a bot turn (Thinking -> Tool Calls -> Success/Error/Cancelled).
- **StatusLine:** Represents a tool execution event.

## 3. Integration Points / API Contract

### 3.1 Tool Interception & HITL Bridge
The `ToolWrapper` [PENDING LINK] intercepts tool calls from the Core Engine [PENDING LINK].

1. **`request_tool_approval(tool_name, args)`**:
    - Async method in `ChatUI`.
    - Displays `ApprovalDialog`.
    - Uses a thread-safe bridge (e.g., `queue.Queue`) to communicate with the synchronous tool execution thread.
2. **`notify_tool(status, ...)`**:
    - Updates the UI with tool execution progress.

### 3.2 Automated Testing & Observability
- **Headless Mode:** The TUI supports execution via `run_test` (Textual) to allow assertions without a physical terminal. (FR-16)
- **Transition Hooks:** `ChatUI` emits internal events (e.g., `_test_event_modal_opened`) that tests can subscribe to or wait for. (FR-17)

## 4. Validation Rules / Constraints
- **ID Stability:** `id` attributes for widgets must remain constant across versions to prevent breaking automated tests.
- **Temporal Consistency:** Tool notifications must be processed in order.
- **Thread Safety:** All UI updates from background threads MUST use `call_soon_threadsafe`.
- **HITL Timeout:** 5-minute timeout for user response; defaults to "Deny".
- **Input Sanitization:** Multi-line input must be stripped of leading/trailing whitespace.
- **External Dependencies:**
    - Core Engine [PENDING LINK]
    - Agent Toolsets [PENDING LINK]
