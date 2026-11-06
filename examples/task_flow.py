from ariadne._util import dumps
from ariadne.task import TaskStore, TaskUpdate, RecordEvent, SearchQuery, DemoEmbedder


def main():
    with TaskStore() as store:
        api = store.orchestrator()
        task = api.create_task("demo", "Build project-scoped task search", ["backend"])
        api.update_task(task.id, TaskUpdate(acceptance_criteria=["Filter by project and tag", "Report index coverage"]))
        for sequence, status in [(1, "ready"), (2, "in_progress")]:
            store.recorder().record_event(RecordEvent(f"state-{sequence}", task.id, {"type": "workflow_status_changed", "sequence": sequence, "status": status}, "demo-run"))
        store.recorder().record_event(RecordEvent("finished", task.id, {"type": "workflow_finished", "sequence": 3, "status": "completed", "result_summary": "Synthetic demo completion", "elapsed_time_ms": 25}, "demo-run"))
        store.index_pending(DemoEmbedder(), 200)
        print(dumps(store.semantic_search(SearchQuery("demo", "task search")), pretty=True))


if __name__ == "__main__":
    main()
