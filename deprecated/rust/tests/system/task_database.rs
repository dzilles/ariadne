use super::fixture::{self, Plan};
use ariadne_tasks::task::*;
use serde_json::{Value, json};
use std::{
    collections::{HashMap, HashSet},
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
    sync::atomic::{AtomicUsize, Ordering},
};

struct Database(PathBuf);
impl Database {
    fn empty() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let directory = std::env::temp_dir().join(format!(
            "ariadne-system-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed),
        ));
        std::fs::create_dir(&directory).unwrap();
        Self(directory.join("android-chat.sqlite"))
    }

    fn example() -> Self {
        let database = Self::empty();
        std::fs::copy(fixture_path(), &database.0)
            .expect("The checked-in Android fixture must exist");
        database
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(self.0.parent().unwrap());
    }
}

fn fixture_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/system/fixtures/android-chat.sqlite")
}

fn query(project: &str) -> SearchQuery {
    SearchQuery {
        project_id: project.into(),
        text: None,
        status: None,
        tag: None,
        limit: 200,
    }
}

fn assert_dataset(store: &mut TaskStore, plan: &Plan) {
    let summaries = store
        .orchestrator()
        .search_tasks(&query(&plan.project_id))
        .unwrap();
    assert_eq!(summaries.len(), plan.tasks.len());
    assert!(summaries.len() >= 20);
    let mut tasks = HashMap::new();
    for summary in summaries {
        let task = store.orchestrator().get_task(&summary.id).unwrap();
        let key = task
            .tags
            .iter()
            .find(|tag| tag.starts_with("APP-"))
            .unwrap()
            .clone();
        assert!(tasks.insert(key, task).is_none());
    }
    let ids: HashMap<_, _> = tasks
        .iter()
        .map(|(key, task)| (task.id.as_str(), key.as_str()))
        .collect();
    let mut roots = 0;
    let mut edges = 0;
    for spec in &plan.tasks {
        let task = &tasks[&spec.key];
        assert_eq!(task.project_id, plan.project_id);
        assert_eq!(task.status, spec.state);
        assert!(task.description.contains(&spec.title));
        assert_eq!(task.acceptance_criteria, spec.acceptance_criteria);
        assert!(!task.files.is_empty());
        assert!(task.files.iter().any(|file| file.file.comment.is_some()));
        assert!(task.links.iter().all(|link| link.link.comment.is_some()));
        let actual: HashSet<_> = task
            .relations
            .iter()
            .filter(|r| r.kind == RelationKind::BlockedBy)
            .map(|r| ids[r.task_id.as_str()])
            .collect();
        let expected: HashSet<_> = spec.blocked_by.iter().map(String::as_str).collect();
        assert_eq!(actual, expected, "Dependency mismatch for {}", spec.key);
        let related: HashSet<_> = task
            .relations
            .iter()
            .filter(|r| r.kind == RelationKind::RelatedTo)
            .map(|r| ids[r.task_id.as_str()])
            .collect();
        assert_eq!(
            related,
            spec.related_to.iter().map(String::as_str).collect()
        );
        edges += actual.len();
        if actual.is_empty() {
            roots += 1;
        }
        if task.status != TaskStatus::Draft {
            for prerequisite in actual {
                assert_eq!(tasks[prerequisite].status, TaskStatus::Completed);
            }
        }
        if task.status == TaskStatus::Completed {
            assert!(task.result_summary.as_ref().unwrap().contains("Synthetic"));
            assert!(task.input_tokens.is_some());
            assert!(task.elapsed_time_ms.is_some());
            assert!(
                task.git_refs
                    .iter()
                    .any(|r| r.reference.kind == GitKind::Development)
            );
        }
        if task.status == TaskStatus::Blocked {
            assert!(task.state_reason.is_some());
        }
        assert!(
            store
                .orchestrator()
                .get_history(&task.id, 200)
                .unwrap()
                .len()
                >= 3
        );
    }
    assert_eq!(roots, 1);
    assert!(edges >= tasks.len() - 1);
    let index = store
        .index_status(&plan.project_id, &DemoEmbedder.model().id)
        .unwrap();
    assert!(index.complete);
    assert!(index.sources >= tasks.len() * 2);
    assert!(
        tasks["APP-007"]
            .git_refs
            .iter()
            .any(|r| r.reference.kind == GitKind::Checkpoint)
    );
}

#[test]
fn example_database_matches_the_connected_acyclic_android_plan() {
    let database = Database::example();
    let mut store = TaskStore::open(&database.0).unwrap();
    // read_plan validates topological order, missing targets, and unfinished prerequisites.
    let plan = fixture::read_plan().unwrap();
    assert_dataset(&mut store, &plan);
}

#[test]
fn database_can_be_regenerated_from_the_human_readable_plan() {
    let database = Database::empty();
    let plan = fixture::read_plan().unwrap();
    {
        let mut store = TaskStore::open(&database.0).unwrap();
        let summary = fixture::populate(&mut store, &plan).unwrap();
        assert_eq!(summary.tasks, plan.tasks.len());
        assert_eq!(
            summary.dependency_edges,
            plan.tasks
                .iter()
                .map(|task| task.blocked_by.len())
                .sum::<usize>()
        );
        assert!(fixture::populate(&mut store, &plan).is_err());
    }
    let mut reopened = TaskStore::open(&database.0).unwrap();
    assert_dataset(&mut reopened, &plan);
}

#[test]
fn sample_supports_provider_mcp_and_internet_search_queries() {
    let database = Database::example();
    let mut store = TaskStore::open(&database.0).unwrap();
    for tag in ["providers", "mcp", "internet", "testing", "chat"] {
        let mut request = query("android-ai-chat");
        request.tag = Some(tag.into());
        assert!(
            !store
                .orchestrator()
                .search_tasks(&request)
                .unwrap()
                .is_empty(),
            "Missing feature tag {tag}"
        );
    }
    let mut request = query("android-ai-chat");
    request.text = Some("internet search".into());
    let results = store.semantic_search(&request, &DemoEmbedder).unwrap();
    assert!(results.index.complete);
    assert!(!results.hits.is_empty());
    assert!(results.hits[0].task.tags.contains(&"search".into()));
    request.project_id = "unrelated-project".into();
    assert!(
        store
            .semantic_search(&request, &DemoEmbedder)
            .unwrap()
            .hits
            .is_empty()
    );
}

fn cli(database: &Database, role: &str, request: Value) -> Value {
    let mut child = Command::new(env!("CARGO_BIN_EXE_ariadne-tasks"))
        .args(["--db", database.0.to_str().unwrap(), "--role", role])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    writeln!(child.stdin.take().unwrap(), "{request}").unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    let response: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(response["ok"], true, "{response}");
    response["result"].clone()
}

#[test]
fn copied_fixture_supports_the_cli_workflow_without_modifying_the_original() {
    let original = std::fs::read(fixture_path()).unwrap();
    let database = Database::example();
    let selected = cli(
        &database,
        "orchestrator",
        json!({"op":"search_tasks","project_id":"android-ai-chat","tag":"APP-010"}),
    );
    let id = selected[0]["id"].as_str().unwrap();
    cli(
        &database,
        "orchestrator",
        json!({"op":"add_note","task_id":id,"text":"System-test copy: verify request assembly and persistence."}),
    );
    cli(
        &database,
        "recorder",
        json!({"op":"record_event","event":{
            "id":"system-start-APP-010","task_id":id,"run_id":"system-run-APP-010",
            "change":{"type":"workflow_status_changed","sequence":2,"status":"in_progress","current_step":"code"}
        }}),
    );
    cli(
        &database,
        "recorder",
        json!({"op":"record_event","event":{
            "id":"system-finish-APP-010","task_id":id,"run_id":"system-run-APP-010",
            "change":{"type":"workflow_finished","sequence":3,"status":"completed","result_summary":"System-test result: request assembly and persistence passed mock checks.","elapsed_time_ms":1250}
        }}),
    );
    let status = cli(
        &database,
        "indexer",
        json!({"op":"index_status","project_id":"android-ai-chat"}),
    );
    assert_eq!(status["pending"], 1);
    assert_eq!(status["complete"], false);
    cli(
        &database,
        "indexer",
        json!({"op":"index_pending","limit":200}),
    );
    let task = cli(&database, "orchestrator", json!({"op":"get_task","id":id}));
    assert_eq!(task["status"], "completed");
    assert_eq!(task["elapsed_time_ms"], 1250);
    let search = cli(
        &database,
        "orchestrator",
        json!({"op":"search_tasks","project_id":"android-ai-chat","text":"request assembly","mode":"semantic"}),
    );
    assert_eq!(search["index"]["complete"], true);
    assert!(!search["hits"].as_array().unwrap().is_empty());
    assert_eq!(std::fs::read(fixture_path()).unwrap(), original);
}
