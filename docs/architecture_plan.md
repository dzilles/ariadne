# Ariadne V-Model Architecture Blueprint

This document outlines the architecture for the Ariadne autonomous software lifecycle engine, detailing how agents interact, how the V-Model is mapped to the local ticket system (SQLite), and how traceability is maintained across the lifecycle.

## 1. The V-Model Definition (in SQLite)
The V-Model is physically represented by the Ticket Hierarchy in the local database.

*   **The Epic:** The Orchestrator creates a parent issue representing a feature (e.g., `TUI & Human-in-the-loop`).
*   **The V-Model Sub-Tasks:** The Orchestrator generates child tickets for the sequential phases:
    1.  `[REQ] Requirement Analysis` (Requirement Gathering)
    2.  `[ARCH] System Architecture` (System/Module Design)
    3.  `[DEV] Implementation` (Coding)
    4.  `[TEST] Testing` (Validation)
    5.  `[QA] Quality Assurance` (Verification)

## 2. Gate Enforcement (JIT Validation)
Gates are enforced using **Ticket Relations** combined with **Just-In-Time (JIT) Python decorators**.

*   **The Graph:** Sub-tasks are linked in sequence (ARCH blocked by REQ, DEV blocked by ARCH, etc.).
*   **Guarded Writes:** Write tools (`write_file`, `commit_changes`) are protected by a `@jit_vmodel_guard` decorator. 
*   **Rule Engine:** The guard queries the database for the ticket's status. If the status does not match the allowed phase for that tool (defined in `src/workflows/rules.py`), the action is blocked. 
*   **State Robustness:** The guard must handle `None` states (sync lag) by defaulting to `Backlog` and must enrich simplified API data with full `state_detail` information.

## 3. Autonomous Loop & Escalation (The Orchestrator)
Ariadne operates as an autonomous factory line, driven by the Orchestrator Agent.

*   **Delegation:** The Orchestrator uses a `delegate_to_agent(agent, task)` tool.
*   **Standardized Returns:** Agents must return `[SUCCESS]` upon completion or `[ESCALATION]` if blocked.
*   **Orchestrator Responsibility:** The Orchestrator manages the transition between tickets. It is responsible for moving sub-tasks through their lifecycle and unblocking agents if they hit system limits.

## 4. Agent Responsibilities
*   **Orchestrator Agent:** Backlog management, Epic/Sub-task creation, Stable ID assignment, workflow coordination, and escalation handling.
*   **Requirements Agent:** Generates formal specifications using the REQ template.
*   **Architect Agent:** Designs system components and integration points using the ARCH template.
*   **Developer Agent:** Implements code in `feat/` branches and applies **Traceability Tags**.
*   **Tester Agent:** Writes and executes `pytest` suites in `test/` branches.
*   **QA Agent:** Final audit gate, applying database tags and verifying documentation alignment.

## 5. Traceability & Documentation (Stable IDs)
To prevent documentation from becoming obsolete when tickets are closed, Ariadne uses **Stable Component IDs**.

*   **Functional Naming:** Artifacts are named after the component or requirement ID, NOT the ticket ID.
    *   Requirement: `docs/requirements/REQ-001.md`
    *   Design: `docs/design/ARCH-001.md`
*   **ID Registry:** A global mapping (conceptually) links Stable IDs to features.
*   **Code Tagging:** Developers MUST include a traceability tag in the header of functions or classes:
    ```python
    def some_function():
        """
        Implementation of ARCH-001.
        Fulfills REQ-001.
        """
    ```

### 5.1 Inter-Artifact Linking (The Dependency Web)
Artifacts must be explicitly linked to support impact analysis:
*   **Requirements Linking:** REQ files must list `Refines: REQ-XXX` (if it's a sub-requirement) or `Depends on: REQ-YYY`.
*   **Architecture Refinement:** Every `ARCH-XXX` must contain a `Traces to: REQ-XXX` section, mapping architectural components to specific functional requirements.
*   **Interface Dependencies:** ARCH files must list `Interfaces with: ARCH-ZZZ` to document component cross-dependencies.
*   **Mermaid Visualization:** High-level designs should use Mermaid.js `requirementDiagram` or `classDiagram` to visualize these links within the `.md` files.

## 6. Execution Details

### 6.1 Isolated Git Workflow
1.  **Epic Branch:** `epic/FEATURE-NAME`
2.  **Agent Branches:** `docs/REQ-001`, `feat/FEAT-001`, `test/FEAT-001`.
3.  **Merging:** The Orchestrator performs merges into the Epic branch only after successful phase completion.

### 6.2 Human-in-the-loop (HITL)
*   **Interception:** The `tool_wrapper` intercepts sensitive tool calls.
*   **Approval UI:** A TUI-based `ApprovalDialog` allows the user to `Approve`, `Deny`, or `Allow Session`.
*   **Async Bridge:** A thread-safe queue synchronizes background agent threads with the UI event loop.

## 7. Operational Efficiency
To minimize token waste and prevent agent recursion:
*   **Surgical Delegation:** The Orchestrator provides a **Reference Manifest** (specific files to read) and a **Knowledge Summary** (context already known).
*   **Search-First Protocol:** Agents use `search_file_content` before `read_file`.
*   **Template-First:** Standard templates for REQ and ARCH are embedded in agent system prompts to avoid unnecessary "style" lookups.
