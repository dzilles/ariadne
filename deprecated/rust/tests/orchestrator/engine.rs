use super::support::*;
use ariadne_tasks::{
    Error,
    interaction::{EventKind, Interface},
    llm::{Cancellation, Role},
    orchestrator::{State, TaskTools},
    task::{SearchQuery, TaskStore},
};
use serde_json::json;

#[test]
fn a_chat_turn_creates_a_real_draft_task_and_saves_the_orchestrator_dialogue() {
    let directory = Directory::new();
    directory.initialize();
    let conversation = directory.conversation();
    let script = Script::new(vec![
        calls(vec![(
            "tool-1",
            "create_task",
            json!({"description":"Implement Android chat streaming","tags":["android"]}),
        )]),
        reply("Created the streaming task."),
    ]);
    let (interface, _) = Interface::new(64).unwrap();
    let events = interface.subscribe(&conversation.id).unwrap();
    directory
        .engine()
        .turn(
            &conversation.id,
            "command-1",
            "Create a task for streaming",
            &script.gateway(),
            &interface,
            &Cancellation::default(),
        )
        .unwrap();
    let saved = directory.conversations().get(&conversation.id).unwrap();
    assert_eq!(saved.state, State::Idle);
    assert_eq!(saved.entries.len(), 5);
    let requests = script.requests.lock().unwrap();
    assert_eq!(requests.len(), 2);
    let result = requests[1].1.messages.last().unwrap();
    assert_eq!(result.role, Role::Tool);
    assert!(
        result
            .content
            .as_ref()
            .unwrap()
            .contains("Implement Android chat streaming")
    );
    assert!(requests[0].1.tools.iter().all(|tool| {
        !tool.input_schema["properties"]
            .as_object()
            .unwrap()
            .contains_key("project_id")
    }));
    let mut task_store = TaskStore::open(directory.0.join("tasks.sqlite")).unwrap();
    let tasks = task_store
        .orchestrator()
        .search_tasks(&SearchQuery {
            project_id: "project".into(),
            text: None,
            status: None,
            tag: None,
            limit: 20,
        })
        .unwrap();
    assert_eq!(tasks.len(), 1);
    assert_eq!(tasks[0].status, ariadne_tasks::task::TaskStatus::Draft);
    let mut terminal = 0;
    while let Ok(event) = events.recv_timeout(std::time::Duration::from_millis(10)) {
        if matches!(event.payload, EventKind::RunFinished { .. }) {
            terminal += 1;
        }
    }
    assert_eq!(terminal, 1);
}

#[test]
fn task_access_is_scoped_and_recorder_and_config_edits_are_unavailable() {
    let directory = Directory::new();
    directory.initialize();
    let config = directory.config().load().unwrap().1;
    let mut store = TaskStore::open(directory.0.join("tasks.sqlite")).unwrap();
    let other = store
        .orchestrator()
        .create_task("other", "Private task", vec![])
        .unwrap();
    let mut tools = TaskTools {
        store: &mut store,
        configuration: &config,
        project_id: "project",
        profile_id: "orchestrator",
    };
    for name in ["get_task", "update_task", "get_history"] {
        assert_eq!(
            tools.call(name, json!({"id":other.id})).unwrap_err().code,
            "FORBIDDEN"
        );
    }
    for name in ["add_note", "annotate_reference"] {
        assert_eq!(
            tools
                .call(
                    name,
                    json!({"task_id":other.id,"text":"x","reference_id":"r","comment":"x"})
                )
                .unwrap_err()
                .code,
            "FORBIDDEN"
        );
    }
    for name in [
        "record_event",
        "save_profile",
        "run_command",
        "index_pending",
    ] {
        assert_eq!(tools.call(name, json!({})).unwrap_err().code, "FORBIDDEN");
    }
    assert!(
        tools
            .call(
                "create_task",
                json!({"project_id":"other","description":"escape"})
            )
            .is_err()
    );
    assert!(
        tools
            .call(
                "create_task",
                json!({"description":"bad","status":"completed"})
            )
            .is_err()
    );
}

#[test]
fn model_errors_do_not_erase_user_messages_or_save_partial_replies() {
    let directory = Directory::new();
    directory.initialize();
    let conversation = directory.conversation();
    let script = Script::new(vec![Err(Error::new("RATE_LIMITED", "Try later"))]);
    let (interface, _) = Interface::new(16).unwrap();
    let events = interface.subscribe(&conversation.id).unwrap();
    assert_eq!(
        directory
            .engine()
            .turn(
                &conversation.id,
                "command",
                "hello",
                &script.gateway(),
                &interface,
                &Cancellation::default()
            )
            .unwrap_err()
            .code,
        "RATE_LIMITED"
    );
    let saved = directory.conversations().get(&conversation.id).unwrap();
    assert_eq!(saved.state, State::Failed);
    assert_eq!(saved.entries.len(), 2);
    assert_eq!(saved.entries[1].message.role, Role::User);
    let mut outcomes = 0;
    while let Ok(event) = events.recv_timeout(std::time::Duration::from_millis(10)) {
        if matches!(event.payload, EventKind::RunFinished { .. }) {
            outcomes += 1;
        }
    }
    assert_eq!(outcomes, 1);
}

#[test]
fn a_conversation_keeps_its_snapshot_and_history_while_new_conversations_use_edits() {
    let directory = Directory::new();
    directory.initialize();
    let old = directory.conversation();
    let config = directory.config();
    let mut profile = config.get_profile("orchestrator").unwrap();
    profile.model = Some("example/new-model".into());
    config.save_profile(profile, None).unwrap();
    let mut prompt = config.get_prompt("orchestrator").unwrap();
    prompt.text.push_str("\nNEW-INSTRUCTION");
    config.save_prompt(prompt, None).unwrap();
    let new = directory.conversation();
    let script = Script::new(vec![reply("first"), reply("second"), reply("new")]);
    let (interface, _) = Interface::new(16).unwrap();
    directory
        .engine()
        .turn(
            &old.id,
            "one",
            "remember apples",
            &script.gateway(),
            &interface,
            &Cancellation::default(),
        )
        .unwrap();
    directory
        .engine()
        .turn(
            &old.id,
            "two",
            "what did I say?",
            &script.gateway(),
            &interface,
            &Cancellation::default(),
        )
        .unwrap();
    directory
        .engine()
        .turn(
            &new.id,
            "three",
            "hello",
            &script.gateway(),
            &interface,
            &Cancellation::default(),
        )
        .unwrap();
    let captured = script.requests.lock().unwrap();
    assert_eq!(captured[0].0.model, "example/model");
    assert_eq!(captured[2].0.model, "example/new-model");
    assert!(
        !captured[0].1.messages[0]
            .content
            .as_ref()
            .unwrap()
            .contains("NEW-INSTRUCTION")
    );
    assert!(
        captured[2].1.messages[0]
            .content
            .as_ref()
            .unwrap()
            .contains("NEW-INSTRUCTION")
    );
    assert!(
        captured[1]
            .1
            .messages
            .iter()
            .any(|m| m.content.as_deref() == Some("remember apples"))
    );
    assert!(
        !captured[2]
            .1
            .messages
            .iter()
            .any(|m| m.content.as_deref() == Some("remember apples"))
    );
}

#[test]
fn tool_limits_stop_side_effects_and_close_unexecuted_calls() {
    let directory = Directory::new();
    directory.initialize();
    let config = directory.config();
    let mut profile = config.get_profile("orchestrator").unwrap();
    profile.settings.insert("max_tool_calls".into(), json!(1));
    config.save_profile(profile, None).unwrap();
    let conversation = directory.conversation();
    let script = Script::new(vec![calls(vec![
        ("first", "create_task", json!({"description":"First"})),
        ("second", "create_task", json!({"description":"Second"})),
    ])]);
    let (interface, _) = Interface::new(16).unwrap();
    assert_eq!(
        directory
            .engine()
            .turn(
                &conversation.id,
                "command",
                "create two",
                &script.gateway(),
                &interface,
                &Cancellation::default()
            )
            .unwrap_err()
            .code,
        "TOOL_LIMIT"
    );
    let saved = directory.conversations().get(&conversation.id).unwrap();
    assert_eq!(
        saved
            .entries
            .last()
            .unwrap()
            .message
            .tool_call_id
            .as_deref(),
        Some("second")
    );
    let mut tasks = TaskStore::open(directory.0.join("tasks.sqlite")).unwrap();
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
