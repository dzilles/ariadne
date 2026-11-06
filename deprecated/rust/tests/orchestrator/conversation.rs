use super::support::*;
use ariadne_tasks::{
    interaction::new_id,
    llm::{Message, Role, ToolCall},
    orchestrator::{Entry, State},
    task::{SearchQuery, TaskStore},
};
use serde_json::json;

#[test]
fn conversation_versions_snapshots_and_public_views_survive_restart() {
    let directory = Directory::new();
    directory.initialize();
    let store = directory.conversations();
    let mut conversation = directory.conversation();
    let mut stale = store.get(&conversation.id).unwrap();
    conversation.title = "Updated".into();
    store.save(&mut conversation).unwrap();
    assert_eq!(store.save(&mut stale).unwrap_err().code, "VERSION_CONFLICT");
    let mut assistant = Message::text(Role::Assistant, "Public reply");
    assistant.continuation.insert(
        "reasoning_details".into(),
        json!([{"data":"PRIVATE-CONTINUATION"}]),
    );
    conversation.entries.push(Entry {
        id: new_id("message"),
        message: assistant,
        call_id: Some("call".into()),
        usage: None,
    });
    store.save(&mut conversation).unwrap();
    let reopened = directory.conversations().get(&conversation.id).unwrap();
    assert_eq!(reopened.title, "Updated");
    assert_eq!(reopened.entries.len(), 2);
    let view = reopened.view().to_string();
    assert!(view.contains("Public reply"));
    assert!(!view.contains("PRIVATE-CONTINUATION"));
    assert!(!view.contains("You are Ariadne"));
    assert_eq!(
        directory
            .config()
            .get_snapshot(&reopened.snapshot_id)
            .unwrap()
            .configuration
            .profiles["orchestrator"]
            .model
            .as_deref(),
        Some("example/model")
    );
}

#[test]
fn recovery_closes_ambiguous_tool_calls_without_replaying_them() {
    let directory = Directory::new();
    directory.initialize();
    let store = directory.conversations();
    let mut conversation = directory.conversation();
    let mut tasks = TaskStore::open(directory.0.join("tasks.sqlite")).unwrap();
    tasks
        .orchestrator()
        .create_task("project", "Already performed before interruption", vec![])
        .unwrap();
    let mut message = Message::text(Role::Assistant, "");
    message.tool_calls = vec![ToolCall {
        id: "pending-call".into(),
        name: "create_task".into(),
        arguments: json!({"description":"Already performed before interruption"}).to_string(),
    }];
    conversation.entries.push(Entry {
        id: new_id("message"),
        message,
        call_id: Some("call".into()),
        usage: None,
    });
    conversation.state = State::Running;
    conversation.active_run_id = Some("run".into());
    store.save(&mut conversation).unwrap();
    assert_eq!(store.recover_interrupted().unwrap(), 1);
    assert_eq!(store.recover_interrupted().unwrap(), 0);
    let restored = store.get(&conversation.id).unwrap();
    assert_eq!(restored.state, State::Interrupted);
    assert!(restored.active_run_id.is_none());
    assert_eq!(
        restored
            .entries
            .last()
            .unwrap()
            .message
            .tool_call_id
            .as_deref(),
        Some("pending-call")
    );
    let script = Script::new(vec![reply("I can inspect the task before continuing.")]);
    let (interface, _) = ariadne_tasks::interaction::Interface::new(8).unwrap();
    directory
        .engine()
        .turn(
            &conversation.id,
            "resume",
            "Continue",
            &script.gateway(),
            &interface,
            &Default::default(),
        )
        .unwrap();
    assert_eq!(
        tasks
            .orchestrator()
            .search_tasks(&SearchQuery {
                project_id: "project".into(),
                text: None,
                status: None,
                tag: None,
                limit: 20
            })
            .unwrap()
            .len(),
        1
    );
}
