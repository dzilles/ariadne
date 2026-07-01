# Ariadne Ticket System Specification

This document defines the standardized structure, workflow, and data model for tickets within the Ariadne autonomous lifecycle.

---

## 1. Ticket Structure (Description)

The `description` field of every ticket must follow this Markdown schema to ensure Agents can reliably parse requirements and acceptance criteria.

### Feature / User Story Schema
```markdown
# User Story
**As a** [Role] **I want** [Action/Feature] **So that** [Benefit/Value]

# Acceptance Criteria
- [ ] Criteria 1
- [ ] Criteria 2

# Technical Context
*   **Stable ID:** [e.g., REQ-001]
*   **Module:** [e.g., TUI]
*   **Dependencies:** [e.g., REQ-000, ARCH-005]
```

---

## 2. Workflow & Status Mapping

| Standard Status | Owner Agent | Success Transition |
| :--- | :--- | :--- |
| `Backlog` | **Orchestrator** | `Ready for Analysis` |
| `Ready for Analysis` | **Requirements** | `Ready for Design` |
| `Ready for Design` | **Architect** | `Ready for Development` |
| `Ready for Development`| **Developer** | `Ready for Testing` |
| `Ready for Testing` | **Tester** | `Ready for QA` |
| `Ready for QA` | **QA / Human** | `Done` |

---

## 3. Stable ID & Traceability

Documentation and code are linked to tickets via **Stable IDs**, which persist even after a ticket is closed.

### 3.1 Custom Fields (SQLite)
The following properties must be set on every ticket:
*   **`Stable ID`**: The persistent ID (e.g., `REQ-001`, `ARCH-001`).
*   **`Links to`**: References to parent or related IDs (e.g., `ARCH-001 traces to REQ-001`).

### 3.2 Artifact Naming & Linking
- Requirements: `docs/requirements/REQ-XXX.md`
- Architecture: `docs/design/ARCH-XXX.md`
- **Internal Links:** Every artifact MUST have a "Traceability" section at the bottom listing its parent and children IDs.

---

## 4. Artifact Templates (Traceability Sections)

### REQ-XXX Template Add-on:
```markdown
## Traceability
- **Parent Requirement:** [None or REQ-YYY]
- **Children Designs:** [ARCH-ZZZ]
- **Related Requirements:** [REQ-AAA]
```

### ARCH-XXX Template Add-on:
```markdown
## Traceability
- **Implements:** [REQ-XXX]
- **Interfaces with:** [ARCH-BBB]
- **Implementation:** [File paths or Module names]
```

---

## 5. Agent Mission Protocols

### Requirements Agent
*   **Action:** Creates `docs/requirements/REQ-XXX.md`.
*   **Traceability:** Must explicitly link to the Epic and any parent requirements.

### Architect Agent
*   **Action:** Creates `docs/design/ARCH-XXX.md`.
*   **Traceability:** Must map every architectural component to a Functional Requirement (FR) from the REQ doc.

### Developer Agent
*   **Action:** Implements logic in `src/`.
*   **Traceability:** Adds `Fulfills ARCH-XXX` tags to function docstrings.
