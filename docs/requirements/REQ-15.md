# REQ-15: Terminal User Interface & Human-in-the-loop

## Introduction
This document defines the requirements for the Terminal User Interface (TUI) and Human-in-the-loop (HITL) system. The system provides a real-time monitoring dashboard for autonomous agents and a mechanism for manual intervention during sensitive operations. This version includes enhanced requirements for testability and strict traceability standards to support automated UI testing and maintain code integrity.

## User Requirements (UR)
- **UR-1**: The user must be able to monitor agent activities (logs, tool calls, status) in real-time through a terminal interface.
- **UR-2**: The user must be able to switch between multiple active agents or view a unified dashboard.
- **UR-3**: The user must be able to approve, deny, or grant session-wide permission for tool calls.
- **UR-4**: The user must be able to interact with the system using keyboard shortcuts and slash commands.
- **UR-5**: The user must be able to view and modify system settings at runtime.
- **UR-6**: The user must be able to export and import conversation histories.

## Functional Requirements (FR)
- **FR-1**: The TUI shall display a live stream of agent logs, including tool execution status (start, success, error).
- **FR-2**: The system shall provide slash commands for common actions: `/help`, `/clear`, `/quit`, `/export`, `/import`, `/agent`, and `/settings`.
- **FR-3**: The TUI shall support tab-completion for slash commands and their arguments (e.g., agent names, setting fields).
- **FR-4**: The input area shall support multi-line text entry (Ctrl+Enter for new line, Enter to submit).
- **FR-5**: The system shall maintain an input history navigable with Up/Down arrow keys.
- **FR-6**: The system shall intercept tool calls wrapped with error handling to request user approval.
- **FR-7**: The HITL mechanism shall present a modal dialog showing the tool name, arguments, and provide options: Approve (Yes), Deny (No), and Allow Session.
- **FR-8**: "Allow Session" shall auto-approve all subsequent tool calls for the current session.
- **FR-9**: The system shall support switching the active agent via the `/agent <name>` command.
- **FR-10**: The system shall allow viewing and editing Pydantic-based settings via the `/settings` command.
- **FR-11**: The TUI shall provide an "Abort" action (Escape key) to cancel the current agent task.
- **FR-12**: The system shall record all tool approvals and denials in the agent's audit trail/logs.
- **FR-13 (Testability - State Exposure)**: The TUI shall expose its internal state (e.g., current active agent, log content, modal status, input buffer) via a queryable interface (e.g., a `get_state()` method) for automated testing.
- **FR-14 (Testability - Component IDs)**: All interactive UI components (buttons, input fields, modals, containers) shall have unique, stable `id` attributes to facilitate targeted selection in automated UI tests.
- **FR-15 (Testability - Input Simulation)**: The TUI shall provide programmatic methods to simulate user input (e.g., `simulate_keypress(key)`, `simulate_input(text)`) that bypass physical hardware but trigger the same event logic.
- **FR-16 (Testability - Headless Execution)**: The system shall support a "headless" execution mode (compatible with Textual's `run_test`) where the TUI can be initialized, interacted with, and asserted against without requiring a physical terminal or TTY.
- **FR-17 (Testability - Verification Hooks)**: The TUI shall provide hooks to intercept and verify UI transitions (e.g., "modal_opened", "message_received") to allow tests to wait for specific UI states before proceeding.

## Non-Functional Requirements (NFR)
- **NFR-1 (Performance)**: The TUI must be lightweight and not introduce significant latency to agent execution (except when waiting for HITL approval).
- **NFR-2 (Usability)**: The interface should use Rich text for clear visual distinction between user messages, bot responses, and tool statuses.
- **NFR-3 (Reliability)**: The HITL mechanism must use thread-safe communication (e.g., thread-safe queues) to bridge sync tool calls with the async UI event loop.
- **NFR-4 (Persistence)**: Exported conversation history must be saved in a standard JSON format.
- **NFR-5 (Modularity)**: The TUI code shall be structured to allow for unit testing of individual logic components (e.g., command parsers, log formatters, state managers) independently of the Textual event loop.
- **NFR-6 (Traceability Standards)**: All implementation code must include traceability tags (e.g., `[REQ-15-FR-01]`) to link code blocks to their corresponding requirements. These tags MUST be placed STRICTLY within Python docstrings to avoid syntax errors.

## Assumptions & Constraints
- **Constraint-1**: The TUI is built using the Textual framework and requires a terminal that supports ANSI escape codes.
- **Constraint-2**: HITL approval is synchronous from the agent's perspective; the agent pauses until the user responds or a timeout occurs.
- **Constraint-3 (Traceability Tag Placement)**: All traceability tags in Python source code MUST be placed exclusively within docstrings to avoid syntax errors or interference with executable code. This is a mandatory requirement to prevent previous issues where tags in the code body caused failures.
- **Assumption-1**: Agents use the provided `tool_wrapper` or a compatible mechanism for tool interception.

## Traceability
- **Parent Requirement:** None (Core Feature)
- **Children Designs:** [ARCH-15]
- **Related Requirements:** None
