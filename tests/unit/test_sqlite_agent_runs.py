from src.ariadne.work_items.adapters.sqlite import SQLiteWorkItemStore
from src.ariadne.work_items.models import AgentRunStatus, WorkItemType


def test_sqlite_store_persists_agent_runs(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item("Demo", "Description", WorkItemType.TASK, "Medium")

    run_id = store.start_agent_run(work_item_id, "Developer", "Build it")
    store.finish_agent_run(
        run_id,
        AgentRunStatus.SUCCESS,
        {"status": "SUCCESS", "summary": "Done"},
        {"branch": "main", "changed_files": ["src/app.py"]},
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
    assert runs[0].finished_at


def test_sqlite_store_persists_context_entries(tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item("Demo", "Description", WorkItemType.TASK, "Medium")

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
    work_item_id = store.create_work_item("Demo", "Description", WorkItemType.TASK, "Medium")
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
    work_item_id = store.create_work_item("Demo", "Description", WorkItemType.TASK, "Medium")
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
    work_item_id = store.create_work_item("Demo", "Description", WorkItemType.TASK, "Medium")
    first_run_id = store.start_agent_run(work_item_id, "Requirements", "Write requirements")
    second_run_id = store.start_agent_run(work_item_id, "Requirements", "Revise requirements")

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
