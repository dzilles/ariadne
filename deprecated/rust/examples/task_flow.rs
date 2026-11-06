use ariadne_tasks::task::*;

fn main() -> Result<()> {
    let mut store = TaskStore::open(":memory:")?;
    store.register_embedding_model(&DemoEmbedder.model())?;
    let task = store.orchestrator().create_task(
        "demo-project",
        "Build search for stored tasks",
        vec!["backend".into()],
    )?;
    store.orchestrator().add_note(
        &task.id,
        "Search results must be restricted to the active project",
    )?;
    for (sequence, status) in [(1, TaskStatus::Ready), (2, TaskStatus::InProgress)] {
        store.recorder().record_event(RecordEvent {
            id: format!("status-{sequence}"),
            task_id: task.id.clone(),
            run_id: Some("run-1".into()),
            change: RecordedChange::WorkflowStatusChanged {
                sequence,
                status,
                current_step: Some("code".into()),
                state_reason: None,
            },
        })?;
    }
    store.recorder().record_event(RecordEvent {
        id: "usage-1".into(),
        task_id: task.id.clone(),
        run_id: Some("run-1".into()),
        change: RecordedChange::UsageRecorded {
            model_call_id: "call-1".into(),
            input_tokens: Some(120),
            output_tokens: Some(40),
        },
    })?;
    store.recorder().record_event(RecordEvent {
        id: "finished-1".into(),
        task_id: task.id.clone(),
        run_id: Some("run-1".into()),
        change: RecordedChange::WorkflowFinished {
            sequence: 3,
            status: TaskStatus::Completed,
            result_summary: "Task search implemented and project filtering tested".into(),
            elapsed_time_ms: 1500,
        },
    })?;
    println!(
        "Before indexing: {}",
        serde_json::to_string(&store.index_status("demo-project", &DemoEmbedder.model().id)?)?
    );
    store.index_pending(&DemoEmbedder, 200)?;
    let results = store.semantic_search(
        &SearchQuery {
            project_id: "demo-project".into(),
            text: Some("task search".into()),
            status: None,
            tag: None,
            limit: 20,
        },
        &DemoEmbedder,
    )?;
    println!(
        "Vector search (token-hash demo): {}",
        serde_json::to_string_pretty(&results)?
    );
    println!(
        "Task: {}",
        serde_json::to_string_pretty(&store.orchestrator().get_task(&task.id)?)?
    );
    Ok(())
}
