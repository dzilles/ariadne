# REQ-15: Terminal User Interface & Human-in-the-loop

## Introduction
This document defines the requirements for the Terminal User Interface (TUI) and Human-in-the-loop (HITL) system. The system provides a real-time monitoring dashboard for autonomous agents and a mechanism for manual intervention during sensitive operations.

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
- **FR-13**: **State Exposure**: TUI components shall expose their internal state through a `get_state()` method to facilitate automated testing.
- **FR-14**: **Stable Component IDs**: All major TUI components (e.g., input area, log display, HITL modal) shall have stable, unique `id` attributes for reliable selection in tests.
- **FR-15**: **Programmatic Input Simulation**: The system shall allow simulating user input (keystrokes, commands) programmatically for automated UI testing.
- **FR-16**: **Headless Execution**: The TUI shall be compatible with headless execution modes (e.g., Textual's `run_test`) to allow running tests in CI environments without a physical terminal.
- **FR-17**: **Verification Hooks**: The TUI shall provide hooks or events to signal when a UI transition (e.g., opening a modal, updating a log) is complete.

## Non-Functional Requirements (NFR)
- **NFR-1**: **Performance**: The TUI must be lightweight and not introduce significant latency to agent execution (except when waiting for HITL approval).
- **NFR-2**: **Usability**: The interface should use Rich text for clear visual distinction between user messages, bot responses, and tool statuses.
- **NFR-3**: **Reliability**: The HITL mechanism must use thread-safe communication to bridge sync tool calls with the async UI event loop.
- **NFR-4**: **Persistence**: Exported conversation history must be saved in a standard JSON format.
- **NFR-5**: **Component-Level Testability**: The TUI shall be designed as a collection of testable components with clear interfaces.
- **NFR-6**: **Traceability**: All implementation code must include traceability tags (e.g., `[REQ-15]`) to link code blocks to their corresponding requirements.

## Assumptions & Constraints
- **Constraint-1**: The TUI is built using the Textual framework and requires a terminal that supports ANSI escape codes.
- **Constraint-2**: HITL approval is synchronous from the agent's perspective; the agent pauses until the user responds or a timeout occurs.
- **Constraint-3**: **Traceability Tag Placement**: All traceability tags in Python source code MUST be placed exclusively within docstrings to avoid syntax errors or interference with executable code.
- **Assumption-1**: Agents use the provided `tool_wrapper` or a compatible mechanism for tool interception.

## Traceability
- **Parent Requirement:** None (Core Feature)
- **Children Designs:** [ARCH-15]
- **Related Requirements:** None
