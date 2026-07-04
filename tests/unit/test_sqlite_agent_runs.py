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
