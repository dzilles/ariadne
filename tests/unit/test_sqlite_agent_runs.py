import sqlite3

import pytest

from src.ariadne.work_items.adapters.sqlite import SQLiteWorkItemStore
from src.ariadne.work_items.models import (
    AgentCompletion,
    AgentRunFinalization,
    AgentRunStatus,
    WorkItemRelationshipType,
    WorkItemStatus,
    WorkItemType,
)


def test_sqlite_store_persists_agent_runs(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )

    run_id = store.start_agent_run(work_item_id, "Developer", "Build it")
    store.finish_agent_run(
        run_id,
        AgentRunStatus.SUCCESS,
        {"status": "SUCCESS", "summary": "Done"},
        {"branch": "main", "changed_files": ["src/app.py"]},
        exit_status="Ready for Testing",
        raw_response="[AGENT_RUN_COMPLETE]",
        diagnostics={"raw_response_truncated": False},
    )

    runs = store.list_agent_runs(work_item_id)

    assert len(runs) == 1
    assert runs[0].id == run_id
    assert runs[0].work_item_id == work_item_id
    assert runs[0].agent_name == "Developer"
    assert runs[0].status == AgentRunStatus.SUCCESS
    assert runs[0].task_description == "Build it"
    assert runs[0].completion_payload["summary"] == "Done"
    assert runs[0].evidence["changed_files"] == ["src/app.py"]
    assert runs[0].entry_status == "Backlog"
    assert runs[0].exit_status == "Ready for Testing"
    assert runs[0].raw_response == "[AGENT_RUN_COMPLETE]"
    assert runs[0].diagnostics == {"raw_response_truncated": False}
    assert runs[0].finished_at

    work_item = store.get_work_item(work_item_id)
    assert work_item.priority == "Medium"


def test_sqlite_store_persists_context_entries(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )

    entry_id = store.add_context_entry(
        work_item_id,
        "Developer",
        "Implemented the endpoint.",
        kind="handoff",
        metadata={"files": ["src/app.py"]},
    )

    entries = store.list_context_entries(work_item_id)

    assert len(entries) == 1
    assert entries[0].id == entry_id
    assert entries[0].work_item_id == work_item_id
    assert entries[0].author == "Developer"
    assert entries[0].kind == "handoff"
    assert entries[0].content == "Implemented the endpoint."
    assert entries[0].metadata["files"] == ["src/app.py"]


def test_append_shared_context_keeps_structured_context_in_sync(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )
    run_id = store.start_agent_run(work_item_id, "Architect", "Design it")

    store.append_shared_context(
        work_item_id,
        "Architect",
        "Use the existing parser.",
        agent_run_id=run_id,
        metadata={"status": "SUCCESS", "changed_files": ["docs/design.md"]},
    )

    work_item = store.get_work_item(work_item_id)
    entries = store.list_context_entries(work_item_id)

    assert "[Architect]" in work_item.shared_context
    assert "Use the existing parser." in work_item.shared_context
    assert len(entries) == 1
    assert entries[0].author == "Architect"
    assert entries[0].kind == "handoff"
    assert entries[0].content == "Use the existing parser."
    assert entries[0].agent_run_id == run_id
    assert entries[0].metadata == {
        "status": "SUCCESS",
        "changed_files": ["docs/design.md"],
    }


def test_sqlite_store_persists_typed_artifact_metadata(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )
    run_id = store.start_agent_run(work_item_id, "Requirements", "Write requirements")

    store.add_artifact_link(
        work_item_id,
        "Requirement",
        "docs/requirements/REQ-1.md",
        artifact_type="requirement",
        agent_run_id=run_id,
        metadata={"phase": "analysis", "stable_id": "REQ-1"},
    )

    work_item = store.get_work_item(work_item_id)

    assert len(work_item.artifacts) == 1
    artifact = work_item.artifacts[0]
    assert artifact.title == "Requirement"
    assert artifact.url == "docs/requirements/REQ-1.md"
    assert artifact.type == "requirement"
    assert artifact.agent_run_id == run_id
    assert artifact.metadata == {"phase": "analysis", "stable_id": "REQ-1"}
    assert artifact.created_at


def test_sqlite_store_updates_duplicate_artifact_links(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )
    first_run_id = store.start_agent_run(
        work_item_id, "Requirements", "Write requirements"
    )
    store.finish_agent_run(
        first_run_id,
        AgentRunStatus.SUCCESS,
        {"status": "SUCCESS", "summary": "Initial requirement"},
        {},
    )
    second_run_id = store.start_agent_run(
        work_item_id, "Requirements", "Revise requirements"
    )

    store.add_artifact_link(
        work_item_id,
        "Requirement",
        "docs/requirements/REQ-1.md",
        artifact_type="requirement",
        agent_run_id=first_run_id,
        metadata={"version": 1},
    )
    store.add_artifact_link(
        work_item_id,
        "Requirement",
        "docs/requirements/REQ-1.md",
        artifact_type="requirement",
        agent_run_id=second_run_id,
        metadata={"version": 2},
    )

    work_item = store.get_work_item(work_item_id)

    assert len(work_item.artifacts) == 1
    assert work_item.artifacts[0].agent_run_id == second_run_id
    assert work_item.artifacts[0].metadata == {"version": 2}


def test_sqlite_store_migrates_legacy_agent_run_columns(tmp_path):
    db_path = tmp_path / "ariadne.db"
    SQLiteWorkItemStore(str(db_path))

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE agent_runs")
        conn.execute(
            """
            CREATE TABLE agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                agent_name TEXT NOT NULL,
                status TEXT NOT NULL,
                task_description TEXT DEFAULT '',
                completion_payload TEXT DEFAULT '{}',
                evidence TEXT DEFAULT '{}',
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT DEFAULT ''
            )
            """
        )

    SQLiteWorkItemStore(str(db_path))

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_runs)")}

    assert {"entry_status", "exit_status", "raw_response", "diagnostics"} <= columns


def test_sqlite_store_allows_only_one_running_run_per_work_item(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )
    run_id = store.start_agent_run(work_item_id, "Requirements", "Write it")

    with pytest.raises(ValueError, match=rf"RUNNING agent run #{run_id}"):
        store.start_agent_run(work_item_id, "Developer", "Build it")

    assert store.get_running_agent_run(work_item_id).id == run_id


def test_sqlite_store_reconciles_legacy_duplicate_running_runs(tmp_path):
    db_path = tmp_path / "ariadne.db"
    store = SQLiteWorkItemStore(str(db_path))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX uq_agent_runs_running_ticket")
        for agent_name in ("Requirements", "Developer"):
            conn.execute(
                """
                INSERT INTO agent_runs (
                    ticket_id, agent_name, status, task_description, entry_status
                ) VALUES (?, ?, 'RUNNING', '', 'Backlog')
                """,
                (work_item_id, agent_name),
            )

    migrated = SQLiteWorkItemStore(str(db_path))
    runs = migrated.list_agent_runs(work_item_id)

    assert [run.status for run in runs] == [
        AgentRunStatus.FAILED,
        AgentRunStatus.RUNNING,
    ]
    assert runs[0].diagnostics["failure_kind"] == "migration"
    assert migrated.get_running_agent_run(work_item_id).agent_name == "Developer"
    with sqlite3.connect(db_path) as conn:
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(agent_runs)")}
    assert "uq_agent_runs_running_ticket" in indexes


def test_sqlite_store_tracks_relationship_blockers_until_dependency_is_done(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    source_id = store.create_work_item(
        "Source", "Description", WorkItemType.TASK, "Medium"
    )
    dependency_id = store.create_work_item(
        "Dependency", "Description", WorkItemType.TASK, "Medium"
    )

    relationship_id = store.add_work_item_relationship(
        source_id,
        dependency_id,
        WorkItemRelationshipType.DEPENDS_ON,
    )
    duplicate_id = store.add_work_item_relationship(
        source_id,
        dependency_id,
        WorkItemRelationshipType.DEPENDS_ON,
    )

    assert duplicate_id == relationship_id
    assert store.get_blockers(source_id) == [dependency_id]
    assert store.list_work_item_relationships(source_id)[0].relationship_type == (
        WorkItemRelationshipType.DEPENDS_ON
    )

    store.update_status(dependency_id, WorkItemStatus.DONE)

    assert store.get_blockers(source_id) == []


def test_sqlite_store_records_status_history(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )

    store.update_status(work_item_id, WorkItemStatus.READY_FOR_ANALYSIS)

    history = store.list_status_history(work_item_id)
    assert [(entry.from_status, entry.to_status) for entry in history] == [
        ("", WorkItemStatus.BACKLOG.value),
        (WorkItemStatus.BACKLOG.value, WorkItemStatus.READY_FOR_ANALYSIS.value),
    ]
    assert history[-1].reason == "Manual status update"


def test_atomic_success_finalization_applies_all_ticket_changes(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )
    store.update_status(work_item_id, WorkItemStatus.READY_FOR_REVIEW)
    run_id = store.start_agent_run(work_item_id, "QM", "Review requirement")

    store.finalize_agent_run(
        run_id,
        AgentRunFinalization(
            run_status=AgentRunStatus.SUCCESS,
            completion=AgentCompletion.model_validate(
                {
                    "status": "SUCCESS",
                    "summary": "Requirement approved.",
                    "artifacts": [
                        {
                            "title": "Review record",
                            "url": "docs/reviews/REQ-1.md",
                            "type": "review",
                            "stable_id": "REVIEW-1",
                        }
                    ],
                    "gate_decision": {
                        "gate": "analysis",
                        "decision": "Approved",
                        "rationale": "Complete.",
                    },
                }
            ),
            evidence={"latest_commit": "def456"},
            next_status=WorkItemStatus.READY_FOR_DESIGN.value,
            commit_hashes=["def456"],
            handoff_context="Requirement review passed.",
            handoff_metadata={"status": "SUCCESS"},
        ),
    )

    work_item = store.get_work_item(work_item_id)
    run = store.list_agent_runs(work_item_id)[0]
    history = store.list_status_history(work_item_id)
    context = store.list_context_entries(work_item_id)

    assert run.status == AgentRunStatus.SUCCESS
    assert run.exit_status == WorkItemStatus.READY_FOR_DESIGN.value
    assert work_item.status == WorkItemStatus.READY_FOR_DESIGN.value
    assert work_item.gate_analysis_status.value == "Approved"
    assert work_item.commit_hashes == ["def456"]
    assert work_item.artifacts[0].agent_run_id == run_id
    assert work_item.artifacts[0].metadata["stable_id"] == "REVIEW-1"
    assert context[0].agent_run_id == run_id
    assert history[-1].agent_run_id == run_id


def test_atomic_failure_finalization_blocks_and_preserves_recovery_data(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )
    store.update_status(work_item_id, WorkItemStatus.READY_FOR_DEVELOPMENT)
    run_id = store.start_agent_run(work_item_id, "Developer", "Build it")

    store.finalize_agent_run(
        run_id,
        AgentRunFinalization(
            run_status=AgentRunStatus.FAILED,
            completion=AgentCompletion.model_validate(
                {
                    "status": "FAILED",
                    "summary": "Tests failed.",
                    "blockers": ["Fix parser regression."],
                    "artifacts": [{"title": "Partial output", "url": "src/parser.py"}],
                }
            ),
            evidence={"status_short": " M src/parser.py"},
            exit_status=WorkItemStatus.BLOCKED.value,
            resumable_status=WorkItemStatus.READY_FOR_DEVELOPMENT.value,
            blocked_reason="Tests failed. | Fix parser regression.",
            commit_hashes=["partial123"],
            comment="Delegated agent failed.\nSummary: Tests failed.",
            handoff_context="Partial implementation remains in the worktree.",
            handoff_metadata={"status": "FAILED"},
            diagnostics={"failure_kind": "postcondition_failure"},
        ),
    )

    work_item = store.get_work_item(work_item_id)
    run = store.list_agent_runs(work_item_id)[0]

    assert run.status == AgentRunStatus.FAILED
    assert run.diagnostics["failure_kind"] == "postcondition_failure"
    assert work_item.status == WorkItemStatus.BLOCKED.value
    assert work_item.resumable_status == WorkItemStatus.READY_FOR_DEVELOPMENT.value
    assert "Fix parser regression" in work_item.blocked_reason
    assert work_item.commit_hashes == []
    assert work_item.artifacts == []
    assert "Tests failed" in work_item.comments[0].text
    assert store.list_context_entries(work_item_id)[0].metadata["status"] == "FAILED"


def test_atomic_cancellation_keeps_entry_status(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )
    store.update_status(work_item_id, WorkItemStatus.READY_FOR_TESTING)
    run_id = store.start_agent_run(work_item_id, "Tester", "Test it")

    store.finalize_agent_run(
        run_id,
        AgentRunFinalization(
            run_status=AgentRunStatus.CANCELLED,
            completion=AgentCompletion(
                status="FAILED",
                summary="Cancelled.",
            ),
            evidence={"status_short": " M tests/test_demo.py"},
            next_status=WorkItemStatus.DONE.value,
            handoff_context="Cancellation recovery evidence.",
        ),
    )

    assert store.get_work_item(work_item_id).status == (
        WorkItemStatus.READY_FOR_TESTING.value
    )
    assert store.list_agent_runs(work_item_id)[0].status == AgentRunStatus.CANCELLED


def test_atomic_finalization_rolls_back_every_change_on_error(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )
    store.update_status(work_item_id, WorkItemStatus.READY_FOR_REVIEW)
    run_id = store.start_agent_run(work_item_id, "QM", "Review it")
    history_count = len(store.list_status_history(work_item_id))

    finalization = AgentRunFinalization(
        run_status=AgentRunStatus.SUCCESS,
        completion=AgentCompletion.model_validate(
            {
                "status": "SUCCESS",
                "summary": "Done.",
                "artifacts": [{"title": "Review", "url": "docs/review.md"}],
                "gate_decision": {"gate": "unknown", "decision": "Approved"},
            }
        ),
        next_status=WorkItemStatus.READY_FOR_DESIGN.value,
        commit_hashes=["def456"],
        handoff_context="Must also roll back.",
    )

    with pytest.raises(ValueError, match="Invalid gate name"):
        store.finalize_agent_run(run_id, finalization)

    work_item = store.get_work_item(work_item_id)
    run = store.list_agent_runs(work_item_id)[0]
    assert run.status == AgentRunStatus.RUNNING
    assert work_item.status == WorkItemStatus.READY_FOR_REVIEW.value
    assert work_item.commit_hashes == []
    assert work_item.artifacts == []
    assert store.list_context_entries(work_item_id) == []
    assert len(store.list_status_history(work_item_id)) == history_count


def test_atomic_finalization_rejects_stale_ticket_status(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Demo", "Description", WorkItemType.TASK, "Medium"
    )
    store.update_status(work_item_id, WorkItemStatus.READY_FOR_ANALYSIS)
    run_id = store.start_agent_run(work_item_id, "Requirements", "Write it")
    store.update_status(work_item_id, WorkItemStatus.READY_FOR_REVIEW)

    finalization = AgentRunFinalization(
        run_status=AgentRunStatus.SUCCESS,
        completion=AgentCompletion(status="SUCCESS", summary="Done."),
        next_status=WorkItemStatus.READY_FOR_REVIEW.value,
    )

    with pytest.raises(ValueError, match="refusing stale finalization"):
        store.finalize_agent_run(run_id, finalization)

    assert store.list_agent_runs(work_item_id)[0].status == AgentRunStatus.RUNNING
    assert store.get_work_item(work_item_id).status == (
        WorkItemStatus.READY_FOR_REVIEW.value
    )


def test_finalization_contract_rejects_inconsistent_terminal_statuses():
    with pytest.raises(ValueError, match="requires completion status FAILED"):
        AgentRunFinalization(
            run_status=AgentRunStatus.FAILED,
            completion=AgentCompletion(status="SUCCESS", summary="Contradiction."),
        )

    with pytest.raises(ValueError, match="terminal run status"):
        AgentRunFinalization(
            run_status=AgentRunStatus.RUNNING,
            completion=AgentCompletion(status="FAILED", summary="Not terminal."),
        )
