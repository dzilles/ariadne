use super::*;

#[test]
fn failure_after_source_update_rolls_back_task_vectors_jobs_and_history() {
    let mut db = TaskStore::open(":memory:").unwrap();
    db.register_embedding_model(&DemoEmbedder.model()).unwrap();
    let task = db
        .orchestrator()
        .create_task("project", "Original task", vec![])
        .unwrap();
    db.index_pending(&DemoEmbedder, 200).unwrap();
    db.db
        .exec(
            "CREATE TRIGGER fail_history BEFORE INSERT ON history
        WHEN json_extract(NEW.data,'$.type')='task_updated'
        BEGIN SELECT RAISE(ABORT,'injected failure after source/job update'); END;",
        )
        .unwrap();
    let error = db
        .orchestrator()
        .update_task(
            &task.id,
            TaskUpdate {
                description: Some("Replacement task".into()),
                ..Default::default()
            },
        )
        .unwrap_err();
    assert_eq!(error.code, "DATABASE_ERROR");
    let stored = db.orchestrator().get_task(&task.id).unwrap();
    assert_eq!(stored.description, task.description);
    assert_eq!(stored.version, task.version);
    assert!(
        db.index_status("project", &DemoEmbedder.model().id)
            .unwrap()
            .complete
    );
    assert_eq!(
        db.orchestrator().get_history(&task.id, 20).unwrap().len(),
        1
    );
    let query = SearchQuery {
        project_id: "project".into(),
        text: Some("Original".into()),
        status: None,
        tag: None,
        limit: 20,
    };
    assert_eq!(
        db.semantic_search(&query, &DemoEmbedder).unwrap().hits[0]
            .task
            .description,
        "Original task"
    );
}

#[test]
fn vector_publication_and_queue_acknowledgement_are_atomic() {
    let mut db = TaskStore::open(":memory:").unwrap();
    db.register_embedding_model(&DemoEmbedder.model()).unwrap();
    db.orchestrator()
        .create_task("project", "Atomic vector publishing", vec![])
        .unwrap();
    let job = db
        .pending_embeddings(&DemoEmbedder.model().id, 20)
        .unwrap()
        .remove(0);
    let vector = DemoEmbedder.embed(&job.content).unwrap();
    db.db
        .exec(
            "CREATE TRIGGER fail_ack BEFORE DELETE ON embedding_jobs
        BEGIN SELECT RAISE(ABORT,'injected failure after vector publication'); END;",
        )
        .unwrap();
    assert!(db.complete_embedding(&job, &vector).is_err());
    let status = db
        .index_status("project", &DemoEmbedder.model().id)
        .unwrap();
    assert_eq!(status.ready, 0);
    assert_eq!(status.pending, 1);
    db.db.exec("DROP TRIGGER fail_ack").unwrap();
    assert_eq!(
        db.complete_embedding(&job, &vector).unwrap(),
        EmbeddingOutcome::Applied
    );
    assert!(
        db.index_status("project", &DemoEmbedder.model().id)
            .unwrap()
            .complete
    );
    assert!(
        db.db
            .query("PRAGMA foreign_key_check", &[])
            .unwrap()
            .is_empty()
    );
}
