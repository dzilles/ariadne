use serde_json::{Value, json};
use std::{
    io::Write,
    process::{Command, Stdio},
};

fn requests(role: &str, input: &[Value]) -> Vec<Value> {
    let mut child = Command::new(env!("CARGO_BIN_EXE_ariadne-tasks"))
        .args(["--db", ":memory:", "--role", role])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    {
        let mut stdin = child.stdin.take().unwrap();
        for value in input {
            writeln!(stdin, "{value}").unwrap();
        }
    }
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

#[test]
fn llm_role_rejects_recorder_operations_and_unknown_write_fields() {
    let responses = requests(
        "orchestrator",
        &[
            json!({"op":"create_task","project_id":"demo","description":"Build a task prototype"}),
            json!({"op":"record_event","event":{"id":"e","task_id":"t","change":{"type":"agent_result_recorded","summary":"done"}}}),
            json!({"op":"update_task","id":"t","status":"completed"}),
            json!({"op":"search_tasks","project_id":"demo"}),
        ],
    );
    assert_eq!(responses[0]["result"]["status"], "draft");
    assert_eq!(responses[1]["error"]["code"], "FORBIDDEN");
    assert_eq!(responses[2]["error"]["code"], "VALIDATION_ERROR");
    assert_eq!(responses[3]["result"].as_array().unwrap().len(), 1);
}

#[test]
fn internal_roles_do_not_expose_task_definition_writes() {
    for role in ["recorder", "indexer"] {
        let result = requests(
            role,
            &[json!({"op":"create_task","project_id":"p","description":"not permitted"})],
        );
        assert_eq!(result[0]["error"]["code"], "FORBIDDEN");
    }
}

#[test]
fn tool_catalog_only_contains_orchestrator_tools() {
    let output = Command::new(env!("CARGO_BIN_EXE_ariadne-tasks"))
        .arg("--tools")
        .output()
        .unwrap();
    assert!(output.status.success());
    let tools: Vec<Value> = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(tools.len(), 7);
    assert!(
        tools
            .iter()
            .all(|tool| tool["input_schema"]["additionalProperties"] == false)
    );
    assert!(!tools.iter().any(|tool| tool["name"] == "record_event"));
}
