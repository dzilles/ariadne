use super::support::*;
use std::{
    io::Write,
    process::{Command, Stdio},
};

#[test]
fn terminal_frontend_reports_missing_credentials_and_retains_the_user_message() {
    let directory = Directory::new();
    directory.initialize();
    let mut process = Command::new(env!("CARGO_BIN_EXE_ariadne-tasks"))
        .args([
            "chat",
            "--terminal",
            "--root",
            directory.0.join("config").to_str().unwrap(),
            "--db",
            directory.0.join("tasks.sqlite").to_str().unwrap(),
            "--project",
            "project",
        ])
        .env_remove("OPENROUTER_API_KEY")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    process
        .stdin
        .take()
        .unwrap()
        .write_all(b"Hello Ariadne\n")
        .unwrap();
    let output = process.wait_with_output().unwrap();
    assert!(output.status.success());
    assert!(
        String::from_utf8(output.stdout)
            .unwrap()
            .contains("ariadne>")
    );
    assert!(
        String::from_utf8(output.stderr)
            .unwrap()
            .contains("AUTHENTICATION_ERROR")
    );
    let store = ariadne_tasks::orchestrator::ConversationStore::open(
        directory.0.join("config/orchestrator.sqlite"),
    )
    .unwrap();
    let conversations = store.list("project").unwrap();
    assert_eq!(conversations.len(), 1);
    assert_eq!(
        conversations[0].entries[1].message.content.as_deref(),
        Some("Hello Ariadne")
    );
}
