use ariadne_tasks::task::*;
use std::{
    path::PathBuf,
    sync::atomic::{AtomicUsize, Ordering},
};

struct Database(PathBuf);
impl Database {
    fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let directory = std::env::temp_dir().join(format!(
            "ariadne-test-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&directory).unwrap();
        Self(directory.join("tasks.sqlite"))
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(self.0.parent().unwrap());
    }
}

fn store() -> TaskStore {
    let mut store = TaskStore::open(":memory:").unwrap();
    store
        .register_embedding_model(&DemoEmbedder.model())
        .unwrap();
    store
}
fn create(store: &mut TaskStore, text: &str) -> Task {
    store
        .orchestrator()
        .create_task("project", text, vec![])
        .unwrap()
}
fn query(text: &str) -> SearchQuery {
    SearchQuery {
        project_id: "project".into(),
        text: Some(text.into()),
        status: None,
        tag: None,
        limit: 20,
    }
}
fn file(path: &str) -> FileInput {
    FileInput {
        repository_id: "repo".into(),
        path: path.into(),
        commit_hash: None,
        symbol: None,
        start_line: None,
        end_line: None,
        comment: None,
    }
}
fn event(task: &Task, id: &str, change: RecordedChange) -> RecordEvent {
    RecordEvent {
        id: id.into(),
        task_id: task.id.clone(),
        run_id: Some("run-1".into()),
        change,
    }
}
fn status(sequence: u64, status: TaskStatus) -> RecordedChange {
    RecordedChange::WorkflowStatusChanged {
        sequence,
        status,
        current_step: None,
        state_reason: None,
    }
}

#[test]
fn crud_preserves_observations_and_reference_identity() {
    let mut db = store();
    let task = create(&mut db, "Implement task search");
    let updated = db
        .orchestrator()
        .update_task(
            &task.id,
            TaskUpdate {
                acceptance_criteria: Some(vec!["Filter by project".into()]),
                tags: Some(vec!["backend".into()]),
                links: Some(vec![LinkInput {
                    url: "https://example.com/spec".into(),
                    label: Some("Spec".into()),
                    comment: None,
                }]),
                files: Some(vec![file("src/lib.rs")]),
                ..Default::default()
            },
        )
        .unwrap();
    let link_id = updated.links[0].id.clone();
    db.recorder()
        .record_event(event(
            &task,
            "read-file",
            RecordedChange::FilesObserved {
                files: vec![ObservedFile {
                    relation: FileRelation::Consulted,
                    file: file("src/store.rs"),
                }],
            },
        ))
        .unwrap();
    let task = db.orchestrator().get_task(&task.id).unwrap();
    let observed_id = task
        .files
        .iter()
        .find(|f| f.relation == FileRelation::Consulted)
        .unwrap()
        .id
        .clone();
    db.orchestrator()
        .annotate_reference(&task.id, &observed_id, "Database implementation")
        .unwrap();
    let task = db
        .orchestrator()
        .update_task(
            &task.id,
            TaskUpdate {
                files: Some(vec![]),
                ..Default::default()
            },
        )
        .unwrap();
    assert_eq!(task.files.len(), 1);
    assert_eq!(
        task.files[0].file.comment.as_deref(),
        Some("Database implementation")
    );
    assert_eq!(task.links[0].id, link_id);
    // Persistence round-trip includes nested/flattened reference structures.
    let task = db.orchestrator().get_task(&task.id).unwrap();
    assert_eq!(task.files[0].id, observed_id);
    db.orchestrator()
        .add_note(&task.id, "Use the customer-approved terminology")
        .unwrap();
    assert_eq!(
        db.orchestrator()
            .search_tasks(&query("customer-approved"))
            .unwrap()
            .len(),
        1
    );
    let history = db.orchestrator().get_history(&task.id, 200).unwrap();
    assert!(history.windows(2).all(|w| w[0].sequence < w[1].sequence));
    assert_eq!(history.last().unwrap().data["type"], "note_added");
}

#[test]
fn rejects_cross_project_relationships_cycles_and_stale_edits() {
    let mut db = store();
    let a = create(&mut db, "Task A");
    let b = create(&mut db, "Task B");
    let other = db
        .orchestrator()
        .create_task("other", "Task C", vec![])
        .unwrap();
    db.orchestrator()
        .update_task(
            &a.id,
            TaskUpdate {
                relations: Some(vec![TaskRelation {
                    task_id: b.id.clone(),
                    kind: RelationKind::BlockedBy,
                }]),
                ..Default::default()
            },
        )
        .unwrap();
    for target in [&a, &other] {
        assert!(
            db.orchestrator()
                .update_task(
                    &b.id,
                    TaskUpdate {
                        relations: Some(vec![TaskRelation {
                            task_id: target.id.clone(),
                            kind: RelationKind::BlockedBy
                        }]),
                        ..Default::default()
                    }
                )
                .is_err()
        );
    }
    assert_eq!(
        db.orchestrator()
            .update_task(
                &a.id,
                TaskUpdate {
                    expected_version: Some(a.version),
                    tags: Some(vec!["changed".into()]),
                    ..Default::default()
                }
            )
            .unwrap_err()
            .code,
        "CONFLICT"
    );
}

#[test]
fn events_and_model_calls_are_idempotent_and_conflicts_roll_back() {
    let mut db = store();
    let task = create(&mut db, "Track model usage");
    let usage = event(
        &task,
        "usage",
        RecordedChange::UsageRecorded {
            model_call_id: "call-1".into(),
            input_tokens: Some(10),
            output_tokens: Some(3),
        },
    );
    assert!(!db.recorder().record_event(usage.clone()).unwrap().duplicate);
    let version = db.orchestrator().get_task(&task.id).unwrap().version;
    assert!(db.recorder().record_event(usage.clone()).unwrap().duplicate);
    assert_eq!(
        db.orchestrator().get_task(&task.id).unwrap().version,
        version
    );
    let mut second = usage.clone();
    second.id = "second-event-same-call".into();
    db.recorder().record_event(second).unwrap();
    assert_eq!(
        db.orchestrator().get_task(&task.id).unwrap().input_tokens,
        Some(10)
    );
    let mut conflict = usage;
    conflict.run_id = Some("another-run".into());
    assert_eq!(
        db.recorder().record_event(conflict).unwrap_err().code,
        "CONFLICT"
    );
    let bad_call = event(
        &task,
        "different-counts",
        RecordedChange::UsageRecorded {
            model_call_id: "call-1".into(),
            input_tokens: Some(20),
            output_tokens: Some(3),
        },
    );
    assert!(db.recorder().record_event(bad_call).is_err());
    assert_eq!(
        db.orchestrator().get_task(&task.id).unwrap().input_tokens,
        Some(10)
    );
}

#[test]
fn missing_measurements_are_not_reported_as_zero() {
    let mut db = store();
    let task = create(&mut db, "Measure unknown usage");
    for (id, input, output) in [("one", Some(10), Some(0)), ("two", None, Some(4))] {
        db.recorder()
            .record_event(event(
                &task,
                id,
                RecordedChange::UsageRecorded {
                    model_call_id: id.into(),
                    input_tokens: input,
                    output_tokens: output,
                },
            ))
            .unwrap();
    }
    let task = db.orchestrator().get_task(&task.id).unwrap();
    assert_eq!(task.input_tokens, None);
    assert_eq!(task.output_tokens, Some(4));
}

#[test]
fn workflow_sequence_and_outcome_are_persistent() {
    let path = Database::new();
    let task;
    {
        let mut db = TaskStore::open(&path.0).unwrap();
        task = create(&mut db, "Complete a workflow");
        // Invalid transition must roll back the sequence allocation as well.
        assert!(
            db.recorder()
                .record_event(event(&task, "bad-start", status(1, TaskStatus::Completed)))
                .is_err()
        );
        db.recorder()
            .record_event(event(&task, "ready", status(1, TaskStatus::Ready)))
            .unwrap();
    }
    let mut db = TaskStore::open(&path.0).unwrap();
    assert!(
        db.recorder()
            .record_event(event(&task, "old", status(1, TaskStatus::Ready)))
            .is_err()
    );
    db.recorder()
        .record_event(event(&task, "start", status(2, TaskStatus::InProgress)))
        .unwrap();
    assert!(
        db.orchestrator()
            .update_task(
                &task.id,
                TaskUpdate {
                    description: Some("Changed goal".into()),
                    ..Default::default()
                }
            )
            .is_err()
    );
    let completed = event(
        &task,
        "complete",
        RecordedChange::WorkflowFinished {
            sequence: 3,
            status: TaskStatus::Completed,
            result_summary: "Checks passed".into(),
            elapsed_time_ms: 500,
        },
    );
    db.recorder().record_event(completed.clone()).unwrap();
    db.recorder().record_event(completed).unwrap();
    let task = db.orchestrator().get_task(&task.id).unwrap();
    assert_eq!(task.elapsed_time_ms, Some(500));
    assert_eq!(task.status, TaskStatus::Completed);
}

#[test]
fn pending_index_work_survives_restart_and_can_be_rebuilt() {
    let path = Database::new();
    {
        let mut db = TaskStore::open(&path.0).unwrap();
        db.register_embedding_model(&DemoEmbedder.model()).unwrap();
        create(&mut db, "Durable database synchronization");
        assert_eq!(
            db.index_status("project", &DemoEmbedder.model().id)
                .unwrap()
                .pending,
            1
        );
    }
    let mut db = TaskStore::open(&path.0).unwrap();
    db.index_pending(&DemoEmbedder, 200).unwrap();
    assert!(
        db.index_status("project", &DemoEmbedder.model().id)
            .unwrap()
            .complete
    );
    assert_eq!(
        db.semantic_search(&query("database"), &DemoEmbedder)
            .unwrap()
            .hits
            .len(),
        1
    );
    db.rebuild_embeddings(&DemoEmbedder.model().id).unwrap();
    assert!(
        db.semantic_search(&query("database"), &DemoEmbedder)
            .unwrap()
            .hits
            .is_empty()
    );
    db.index_pending(&DemoEmbedder, 200).unwrap();
    assert!(
        db.index_status("project", &DemoEmbedder.model().id)
            .unwrap()
            .complete
    );
}

#[test]
fn edit_invalidates_vector_and_rejects_delayed_embedding_from_another_connection() {
    let path = Database::new();
    let mut writer = TaskStore::open(&path.0).unwrap();
    writer
        .register_embedding_model(&DemoEmbedder.model())
        .unwrap();
    let task = create(&mut writer, "Original database design");
    let mut worker = TaskStore::open(&path.0).unwrap();
    let old_job = worker
        .pending_embeddings(&DemoEmbedder.model().id, 20)
        .unwrap()
        .remove(0);
    writer.index_pending(&DemoEmbedder, 200).unwrap();
    writer
        .orchestrator()
        .update_task(
            &task.id,
            TaskUpdate {
                description: Some("New search design".into()),
                ..Default::default()
            },
        )
        .unwrap();
    let results = writer
        .semantic_search(&query("database"), &DemoEmbedder)
        .unwrap();
    assert!(results.hits.is_empty());
    assert!(!results.index.complete);
    let vector = DemoEmbedder.embed(&old_job.content).unwrap();
    assert_eq!(
        worker.complete_embedding(&old_job, &vector).unwrap(),
        EmbeddingOutcome::Obsolete
    );
    assert_eq!(
        writer
            .index_status("project", &DemoEmbedder.model().id)
            .unwrap()
            .pending,
        1
    );
    worker.index_pending(&DemoEmbedder, 200).unwrap();
    let results = writer
        .semantic_search(&query("search"), &DemoEmbedder)
        .unwrap();
    assert!(results.index.complete);
    assert_eq!(results.hits[0].task.description, "New search design");
}

#[test]
fn removal_and_readdition_cannot_resurrect_an_old_job() {
    let mut db = store();
    let task = create(&mut db, "Acceptance criteria test");
    let criteria = || TaskUpdate {
        acceptance_criteria: Some(vec!["Works offline".into()]),
        ..Default::default()
    };
    db.orchestrator().update_task(&task.id, criteria()).unwrap();
    let old_job = db
        .pending_embeddings(&DemoEmbedder.model().id, 20)
        .unwrap()
        .into_iter()
        .find(|j| j.source == "acceptance_criteria")
        .unwrap();
    db.index_pending(&DemoEmbedder, 200).unwrap();
    db.orchestrator()
        .update_task(
            &task.id,
            TaskUpdate {
                acceptance_criteria: Some(vec![]),
                ..Default::default()
            },
        )
        .unwrap();
    assert_eq!(
        db.index_status("project", &DemoEmbedder.model().id)
            .unwrap()
            .sources,
        1
    );
    db.orchestrator().update_task(&task.id, criteria()).unwrap();
    assert_eq!(
        db.complete_embedding(&old_job, &DemoEmbedder.embed(&old_job.content).unwrap())
            .unwrap(),
        EmbeddingOutcome::Obsolete
    );
    assert_eq!(
        db.index_status("project", &DemoEmbedder.model().id)
            .unwrap()
            .pending,
        1
    );
}

#[test]
fn metadata_changes_do_not_reembed_text_and_completion_is_idempotent() {
    let mut db = store();
    let task = create(&mut db, "Unchanged source text");
    let job = db
        .pending_embeddings(&DemoEmbedder.model().id, 20)
        .unwrap()
        .remove(0);
    let vector = DemoEmbedder.embed(&job.content).unwrap();
    assert_eq!(
        db.complete_embedding(&job, &vector).unwrap(),
        EmbeddingOutcome::Applied
    );
    db.orchestrator()
        .add_note(&task.id, "A note is not a description edit")
        .unwrap();
    db.orchestrator()
        .update_task(
            &task.id,
            TaskUpdate {
                tags: Some(vec!["label".into()]),
                ..Default::default()
            },
        )
        .unwrap();
    assert_eq!(
        db.complete_embedding(&job, &vector).unwrap(),
        EmbeddingOutcome::AlreadyApplied
    );
    assert!(
        db.index_status("project", &DemoEmbedder.model().id)
            .unwrap()
            .complete
    );
}

struct FailingEmbedder;
impl Embedder for FailingEmbedder {
    fn model(&self) -> EmbeddingModel {
        DemoEmbedder.model()
    }
    fn embed(&self, _: &str) -> Result<Vec<f32>> {
        Err(Error {
            code: "EMBEDDING_ERROR",
            message: "Temporary service failure".into(),
        })
    }
}

#[test]
fn failed_provider_and_invalid_vectors_leave_jobs_pending() {
    let mut db = store();
    create(&mut db, "Pending vector work");
    assert!(db.index_pending(&FailingEmbedder, 200).is_err());
    let job = db
        .pending_embeddings(&DemoEmbedder.model().id, 20)
        .unwrap()
        .remove(0);
    for vector in [vec![1.0], vec![0.0; 128], vec![f32::NAN; 128]] {
        assert!(db.complete_embedding(&job, &vector).is_err());
    }
    assert_eq!(
        db.index_status("project", &DemoEmbedder.model().id)
            .unwrap()
            .pending,
        1
    );
    db.index_pending(&DemoEmbedder, 200).unwrap();
    assert!(
        db.index_status("project", &DemoEmbedder.model().id)
            .unwrap()
            .complete
    );
}

struct OtherModel;
impl Embedder for OtherModel {
    fn model(&self) -> EmbeddingModel {
        EmbeddingModel {
            id: "other-model-v1".into(),
            dimensions: 2,
        }
    }
    fn embed(&self, _: &str) -> Result<Vec<f32>> {
        Ok(vec![1.0, 0.0])
    }
}

#[test]
fn models_and_projects_are_isolated_and_metadata_filters_use_current_tasks() {
    let mut db = store();
    let task = create(&mut db, "Vector search");
    db.orchestrator()
        .create_task("other-project", "Vector search", vec![])
        .unwrap();
    db.index_pending(&DemoEmbedder, 200).unwrap();
    db.register_embedding_model(&OtherModel.model()).unwrap();
    assert!(
        db.semantic_search(&query("search"), &OtherModel)
            .unwrap()
            .hits
            .is_empty()
    );
    db.index_pending(&OtherModel, 200).unwrap();
    assert_eq!(
        db.semantic_search(&query("search"), &OtherModel)
            .unwrap()
            .hits
            .len(),
        1
    );
    assert!(
        db.register_embedding_model(&EmbeddingModel {
            id: OtherModel.model().id,
            dimensions: 3
        })
        .is_err()
    );
    db.orchestrator()
        .update_task(
            &task.id,
            TaskUpdate {
                tags: Some(vec!["current".into()]),
                ..Default::default()
            },
        )
        .unwrap();
    let mut q = query("search");
    q.tag = Some("current".into());
    assert_eq!(db.semantic_search(&q, &DemoEmbedder).unwrap().hits.len(), 1);
    q.status = Some(TaskStatus::Completed);
    assert!(
        db.semantic_search(&q, &DemoEmbedder)
            .unwrap()
            .hits
            .is_empty()
    );
}

#[test]
fn typed_event_json_roundtrips_file_and_git_observations() {
    let mut db = store();
    let task = create(&mut db, "Observe repository activity");
    let json = serde_json::json!({"id":"file-json","task_id":task.id,"run_id":"run","change":{
        "type":"files_observed","files":[{"relation":"modified","repository_id":"repo","path":"src/main.rs","start_line":1,"end_line":5}]
    }});
    let event: RecordEvent = serde_json::from_value(json).unwrap();
    db.recorder().record_event(event).unwrap();
    db.recorder().record_event(event_for_git(&task)).unwrap();
    let stored = db.orchestrator().get_task(&task.id).unwrap();
    assert_eq!(stored.files[0].file.end_line, Some(5));
    assert_eq!(stored.git_refs[0].reference.kind, GitKind::Checkpoint);
}

fn event_for_git(task: &Task) -> RecordEvent {
    event(
        task,
        "git",
        RecordedChange::GitRecorded {
            reference: GitInput {
                repository_id: "repo".into(),
                commit_hash: "checkpoint-hash".into(),
                kind: GitKind::Checkpoint,
                development_head: Some("development-hash".into()),
            },
        },
    )
}
