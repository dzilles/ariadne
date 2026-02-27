# Ariadne V-Model Architecture Blueprint

This document outlines the planned architecture for the Ariadne autonomous software lifecycle engine, detailing how agents interact, how the V-Model is mapped to the issue tracker (Plane), and how autonomy is achieved.

## 1. The V-Model Definition (in Plane)
The V-Model is physically represented by the Ticket Hierarchy in Plane.

*   **The Epic:** The Product Owner creates a parent issue (e.g., `ISSUE-100: User Authentication`).
*   **The V-Model Sub-Tasks:** The PO (or Orchestrator) generates child tickets for the sequential phases:
    1.  `ISSUE-101`: `[REQ] Define Auth Specs` (Requirement Gathering)
    2.  `ISSUE-102`: `[ARCH] Design Auth System` (System/Module Design)
    3.  `ISSUE-103`: `[DEV] Implement Auth Logic` (Coding)
    4.  `ISSUE-104`: `[TEST] Write Auth Tests` (Validation)
    5.  `ISSUE-105`: `[QA] Review Auth Code` (Verification)

## 2. Gate Enforcement (JIT Validation)
Gates are enforced using Plane's native **Issue Relations** (`blocked_by`) combined with **Just-In-Time (JIT) Python decorators**.

*   **The Graph:** `ISSUE-102` is `blocked_by` `ISSUE-101`. `ISSUE-103` is `blocked_by` `ISSUE-102`.
*   **Unrestricted Reads:** Agents can use read tools (`read_file`, `get_ticket_details`) freely to gather context.
*   **Guarded Writes (Hidden Context):** Write tools (`write_file`, `commit_changes`) are protected by a Python `@jit_vmodel_guard` decorator. To prevent LLM hallucination, agents do *not* pass the `ticket_id` to the tools. Instead, the Orchestrator injects the active `ticket_id` into a secure Python backend context during delegation. The guard checks Plane to ensure the active ticket has no unresolved blockers before allowing the file write.

## 3. Autonomous Loop & Escalation (The Orchestrator)
Ariadne operates as an autonomous factory line, driven by the Orchestrator Agent.

*   **Delegation:** The Orchestrator does not write code. It reads the Epic status and uses a `delegate_to_agent(agent, task)` tool to dispatch the current sub-task to the correct specialized agent.
*   **Standardized Returns:** Agents complete their work and return standardized codes:
    *   `[SUCCESS] Task complete.`
    *   `[ESCALATION] I am blocked because...`
*   **Escalation Protocol:** If an agent hits a JIT block or a missing dependency, it returns an `[ESCALATION]` string. The Orchestrator parses this and re-routes the task (e.g., sending it back to the Architect to fix the missing spec) before asking the Developer to resume.

## 4. Agent Responsibilities
*   **Product Owner (PO):** Interacts with user to create the Parent Epic and the V-Model Sub-tasks. Sets up `blocked_by` relations.
*   **Requirements Agent:** Writes `REQ-*.md` files on an isolated branch.
*   **Architect Agent:** Reads `REQ` files, writes `ARCH-*.md` files (utilizing Mermaid.js) on an isolated branch.
*   **Developer Agent:** Reads specs, writes Python implementation on a `feat/` branch. Uses conventional commits.
*   **Tester Agent:** Reads specs and source code. Writes and runs `pytest` automated tests on a `test/` branch. Strictly prevented from modifying source code.
*   **QA Agent:** The AI Audit Gate. Reviews the merged branches for standards (PEP8), security, and logic.
*   **Orchestrator Agent:** The Scrum Master and Release Manager. Tracks velocity, delegates tasks, manages Git merges between agent branches, and resolves escalations.

## 5. Traceability & Documentation
*   **Traceability:** The Parent Epic ID (`ISSUE-100`) is the ultimate link.
    *   Requirements: `docs/requirements/REQ-100.md`
    *   Architecture: `docs/design/ARCH-100.md`
    *   Code: Branch `feat/ISSUE-100`
    *   Docstrings: `"""Fulfills REQ-100"""`
*   **Plane Audit Trail:** Agents leave HTML-formatted comments when completing tasks, containing links to the generated markdown artifacts or git commit hashes.

## 6. Execution Details & Edge Cases

### 6.1 The Dual-Gate System (Review Flags)
Gate approval and rejections are tracked via strict Plane Labels rather than just state changes.
*   **Review Passed: QA:** Added by the QA Agent when the code/tests pass inspection.
*   **Review Passed: Human:** Added by the Human Operator after the QA Agent approves.
*   **Review Failed: Findings:** Added by either QA or the Human. This explicitly signals to the Orchestrator that the artifact was rejected. The Orchestrator will then re-open the appropriate `[DEV]`, `[TEST]`, or `[ARCH]` ticket and route it back to the agent to fix the findings detailed in the comments.

### 6.2 Isolated Git Workflow (Branch Segregation)
To prevent agents from stepping on each other's toes, Git is used to enforce strict boundaries:
1.  **Epic Branch:** The Orchestrator creates a central integration branch for the Epic (e.g., `epic/ISSUE-100`).
2.  **Agent Branches:** Each agent checks out a sub-branch:
    *   Requirements/Architect: `docs/ISSUE-100`
    *   Developer: `feat/ISSUE-100`
3.  **Tester Branch Sequence:** The Developer finishes `feat/`, and the Orchestrator merges it into `epic/`. The Tester Agent MUST then branch off `epic/ISSUE-100` (creating `test/ISSUE-100`) so it has access to the newly written code to test it.
4.  **Merge Conflicts (Human Intervention):** The Orchestrator acts as the Release Manager. If it attempts to merge an agent's branch into the `epic/` branch and encounters a Git merge conflict, it will immediately abort the operation and pause the autonomous loop. It will alert the human user via the TUI to resolve the conflict manually before continuing.

### 6.3 Documenting QA Findings
*   **Minor Issues:** QA leaves inline comments on the specific Plane sub-task ticket, applying the `Review Failed: Findings` label.
*   **Major/Architectural Flaws:** If QA finds systemic issues, it generates a formal markdown report (e.g., `docs/qa/QA-REPORT-100.md`), commits it to the Epic branch, and links it in the ticket before rejecting it.

### 6.4 Environment & Dependencies (The Playground)
*   **Developer Agent (Playground Access):** The Developer is permitted to modify dependency files (e.g., `requirements.txt`) and run installation commands via the shell tool to build their code.
*   **Tester & QA Agents (Restricted):** The Tester and QA agents must run their checks within the environment defined by the Developer. If a test fails because a dependency is missing, they reject the ticket with `Review Failed: Findings` and route it back to the Developer.
