# ARCH-19: TUI & HITL Refinement (Testability Focus)

## 1. Overview
This architecture refines the Terminal User Interface (TUI) and Human-in-the-loop (HITL) system to enhance testability and robustness, addressing requirements in REQ-16. It introduces a structured approach to state exposure, input simulation, and headless execution, ensuring the system can be thoroughly validated in both development and CI environments.

## 2. Component Design / Data Models

### 2.1 TUI Components (Textual)
All interactive components must use stable `id` attributes for identification in tests (FR-14).

- **ChatUI (App):** The main application container.
    - `id="chat-app"`
    - Responsibility: Manages global state, message routing, and the testability interface.
- **ConversationView (ScrollableContainer):**
    - `id="conversation-view"`
    - Responsibility: Displays the live stream of agent logs and tool execution status (FR-1).
- **ChatInput (Container):**
    - `id="chat-input"`
    - **ChatTextArea:** `id="chat-text-area"`. Supports multi-line entry (FR-4) and history (FR-5).
    - **CommandSuggestions:** `id="command-suggestions"`. Supports tab-completion (FR-3).
- **ApprovalDialog (ModalScreen):**
    - `id="approval-dialog"` (FR-7)
    - **Approve Button:** `id="approve-btn"`
    - **Deny Button:** `id="deny-btn"`
    - **Allow Session Button:** `id="allow-session-btn"`

### 2.2 Testability Interface (FR-13, FR-15, FR-16, FR-17)
To facilitate automated testing, the `ChatUI` class implements the following:

- **State Querying (`get_state()`):** Returns a snapshot of the UI state.
    - Fields: `active_agent`, `is_awaiting_approval`, `current_modal_id`, `message_count`, `input_buffer`.
- **Input Simulation:**
    - `simulate_input(text: str)`: Appends text to the input area and triggers the submit action.
    - `simulate_key(key: str)`: Dispatches a key event to the active widget.
- **Headless Mode:**
    - The TUI supports execution via Textual's `run_test` context manager, allowing for full UI lifecycle testing without a physical terminal.
- **Verification Hooks:**
    - The TUI shall provide callbacks or event listeners (e.g., `on_test_hook(event_name)`) that allow tests to synchronize with UI transitions (FR-17).

### 2.3 Decoupled Components (NFR-5)
To support unit testing, the following logic must be decoupled from the Textual event loop:
- **Command Parser:** A standalone class for parsing slash commands and arguments.
- **Log Formatter:** Functions for converting agent logs/tool calls into Rich-compatible renderables.
- **Settings Manager:** A Pydantic-based handler for viewing and editing system settings (FR-10).

## 3. Integration Points / API Contract

### 3.1 HITL Bridge (NFR-3)
The bridge between the synchronous agent tool calls and the asynchronous TUI uses a thread-safe queue mechanism:
1.  **Request:** Agent thread calls `HITLBridge.request_approval(tool_name, args)`.
2.  **Dispatch:** Bridge uses `app.call_soon_threadsafe` to trigger the `ApprovalDialog` on the TUI thread.
3.  **Wait:** Agent thread blocks on a `threading.Event` or `queue.Queue`.
4.  **Response:** User action in TUI triggers the event/queue, unblocking the agent.

### 3.2 Traceability Tags (NFR-6)
To avoid syntax errors and ensure visibility, all traceability tags MUST be placed within the docstrings of the corresponding classes or functions.

**Example:**
```python
class ChatUI(App):
    """
    Main TUI application.
    
    Traceability: [REQ-16, FR-1, FR-13]
    """
    pass
```

## 4. Validation Rules / Constraints

- **ID Stability:** IDs used for testing (e.g., `id="approve-btn"`) must not be changed without updating the corresponding test suite.
- **Atomic State Updates:** All changes to the UI state that are queried via `get_state()` must be performed atomically to avoid race conditions during testing.
- **Headless Compatibility:** All widgets must be capable of rendering in a headless environment (avoiding direct calls to low-level terminal APIs).
- **Timeout Handling:** HITL approvals must have a configurable timeout (default 5 minutes) to prevent deadlocks in automated environments (FR-12).
- **Docstring Traceability:** NO traceability tags are allowed outside of docstrings (Constraint-3).

## Traceability
- **Implements:** [REQ-16]
- **Refines:** [ARCH-15]
- **Implementation Target:** `src/tui/`
