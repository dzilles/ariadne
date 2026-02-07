# Ariadne Ticket System Specification

This document defines the standardized structure, workflow, and data model for tickets within the Ariadne autonomous lifecycle. This specification is designed to be tool-agnostic, with specific implementation details provided for **Plane**.

---

## 1. Ticket Structure (Description)

The `description` field of every ticket must follow this Markdown schema. This ensures Agents can reliably parse requirements and acceptance criteria.

### Feature / User Story Schema

```markdown
# User Story
**As a** [Role]
**I want** [Action/Feature]
**So that** [Benefit/Value]

# Acceptance Criteria
- [ ] Criteria 1 (Must be verifiable)
- [ ] Criteria 2
- [ ] Criteria 3

# Technical Context (Optional)
*   **Module:** [e.g., Auth, Database]
*   **Constraints:** [e.g., Response < 200ms]
```

### Bug Report Schema

```markdown
# Bug Report
**Description:** [Short summary]
**Severity:** [High/Medium/Low]

# Reproduction Steps
1.  Navigate to...
2.  Click on...
3.  Observe error...

# Expected Behavior
[What should have happened]

# Actual Behavior
[What actually happened]
```

---

## 2. Workflow & Status Mapping

The lifecycle is driven by the **Ticket Status**. Each status corresponds to a specific Agent owner.

| Standard Status | Owner Agent | Trigger Condition | Success Transition | Rejection Transition |
| :--- | :--- | :--- | :--- | :--- |
| `Backlog` | **Product Owner** | Created | `Ready for Analysis` | `Trash` |
| `Ready for Analysis` | **Requirements** | Moved from Backlog | `Ready for Design` | `Backlog` (Clarification) |
| `Ready for Design` | **Architect** | Analysis Approved | `Ready for Development` | `Ready for Analysis` |
| `Ready for Development`| **Developer** | Design Approved | `Ready for Testing` | `Ready for Design` |
| `Ready for Testing` | **Tester** | Implementation Done | `Ready for QA` | `Ready for Development` |
| `Ready for QA` | **QA / Human** | Tests Passed | `Done` | `Ready for Development` |
| `Done` | None | QA Approved | - | - |

---

## 3. Gate & Approval Tracking (Fields)

Approvals and administrative status are tracked via **Structured Fields**, not within the description text.

### Abstract Data Model

The system expects the following keys to be available on a ticket object:

*   `gate_analysis_status`: Enum(`Pending`, `Approved`, `Rejected`)
*   `gate_design_status`: Enum(`Pending`, `Approved`, `Rejected`)
*   `gate_test_status`: Enum(`Pending`, `Approved`, `Rejected`)

### Implementation: Plane

In Plane, these are implemented as **Custom Properties**.

*   **Property Name:** `Analysis Review` (Select)
*   **Property Name:** `Design Review` (Select)
*   **Property Name:** `Test Review` (Select)

---

## 4. Artifact Linking

Agents produce files (Specs, Designs, Tests). These must be linked to the ticket for traceability.

### Abstract Data Model

*   `artifact_links`: List[Object] (`title`, `url`)

### Implementation: Plane

*   Use the native **Links** section of a Ticket.
*   **Format:**
    *   Title: `SPEC-123 (Requirements)`
    *   URL: `https://github.com/.../blob/main/docs/requirements/REQ-123.md` (or local file path reference if no remote)

---

## 5. Agent Responsibilities

### Product Owner (PO)
*   **Input:** Raw user requests.
*   **Action:** Creates tickets, ensures the "User Story" schema is valid.
*   **Output:** Ticket in `Ready for Analysis`.

### Requirements Agent
*   **Input:** Ticket in `Ready for Analysis`.
*   **Action:** Reads User Story, creates `docs/requirements/REQ-{id}.md`.
*   **Gate:** Sets `Analysis Review` = `Approved`.
*   **Output:** Ticket in `Ready for Design` (linked to REQ doc).

### Architect Agent
*   **Input:** Ticket in `Ready for Design`.
*   **Action:** Reads REQ doc, creates `docs/design/DESIGN-{id}.md`.
*   **Gate:** Sets `Design Review` = `Approved`.
*   **Output:** Ticket in `Ready for Development`.

### Developer Agent
*   **Input:** Ticket in `Ready for Development`.
*   **Action:** Reads DESIGN doc, implements code in `src/`.
*   **Output:** Ticket in `Ready for Testing`.

### Tester Agent
*   **Input:** Ticket in `Ready for Testing`.
*   **Action:** Reads Acceptance Criteria, writes/runs tests.
*   **Gate:** Sets `Test Review` = `Approved`.
*   **Output:** Ticket in `Ready for QA`.

### QA Agent
*   **Input:** Ticket in `Ready for QA`.
*   **Action:** Validates all Gates are `Approved` and performs final check.
*   **Output:** Ticket in `Done`.
