use super::support::*;
use serde_json::{Value, json};
use std::{
    io::Write,
    process::{Command, Stdio},
};

fn request(directory: &Directory, role: &str, values: &[Value]) -> Vec<Value> {
    let mut process = Command::new(env!("CARGO_BIN_EXE_ariadne-tasks"))
        .args([
            "config",
            "--root",
            directory.0.to_str().unwrap(),
            "--role",
            role,
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    {
        let mut input = process.stdin.take().unwrap();
        for value in values {
            writeln!(input, "{value}").unwrap();
        }
    }
    let output = process.wait_with_output().unwrap();
    assert!(output.status.success());
    String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

#[test]
fn reader_cannot_edit_but_editor_can_import_and_discover_agent_profiles() {
    let directory = Directory::new();
    let replace =
        json!({"op":"replace_configuration","configuration":configuration(),"expected_revision":0});
    let denied = request(&directory, "reader", std::slice::from_ref(&replace));
    assert_eq!(denied[0]["error"]["code"], "FORBIDDEN");
    let saved = request(&directory, "editor", &[replace]);
    assert_eq!(saved[0]["result"]["revision"], 1);
    let read = request(
        &directory,
        "reader",
        &[
            json!({"op":"list_profiles","component":"agent"}),
            json!({"op":"list_workflows"}),
            json!({"op":"validate"}),
        ],
    );
    assert_eq!(read[0]["result"].as_array().unwrap().len(), 3);
    assert_eq!(read[1]["result"][0]["id"], "code-review-test");
    assert_eq!(read[2]["result"]["revision"], 1);
}

#[test]
fn cli_snapshots_render_fixed_prompts_after_configuration_edits() {
    let directory = Directory::new();
    directory
        .store()
        .replace_configuration(configuration(), None)
        .unwrap();
    let saved = request(&directory, "reader", &[json!({"op":"create_snapshot"})]);
    let snapshot = saved[0]["result"]["id"].as_str().unwrap();
    let prompt = &configuration().prompts["coder"];
    request(
        &directory,
        "editor",
        &[
            json!({"op":"save_prompt","id":"coder","text":format!("{}\nUpdated.", prompt.text),"variables":prompt.variables,"expected_revision":1}),
        ],
    );
    let read = request(
        &directory,
        "reader",
        &[
            json!({"op":"render_profile","id":"coder","variables":coder_inputs(),"snapshot_id":snapshot}),
            json!({"op":"render_profile","id":"coder","variables":coder_inputs()}),
            json!({"op":"save_prompt","id":"p","text":"hello","unexpected":true}),
            json!({"op":"validate"}),
        ],
    );
    assert_eq!(read[0]["result"]["revision"], 1);
    assert!(
        !read[0]["result"]["resolved"]["prompts"][0]["text"]
            .as_str()
            .unwrap()
            .contains("Updated.")
    );
    assert_eq!(read[1]["result"]["revision"], 2);
    assert!(
        read[1]["result"]["resolved"]["prompts"][0]["text"]
            .as_str()
            .unwrap()
            .contains("Updated.")
    );
    assert_eq!(read[2]["error"]["code"], "VALIDATION_ERROR");
    assert_eq!(read[3]["ok"], true);
}

#[test]
fn configuration_tool_catalog_exposes_discovery_without_configuration_writes() {
    let output = Command::new(env!("CARGO_BIN_EXE_ariadne-tasks"))
        .args(["config", "--tools"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let tools: Vec<Value> = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(tools.len(), 4);
    assert!(
        tools
            .iter()
            .all(|tool| !tool["name"].as_str().unwrap().starts_with("save"))
    );
    assert!(
        tools
            .iter()
            .all(|tool| tool["input_schema"]["additionalProperties"] == false)
    );
}

#[test]
fn provider_connection_cli_has_separate_reader_and_editor_access() {
    let directory = Directory::new();
    let provider = &configuration().providers["openrouter"];
    let save = json!({"op":"save_provider","provider":provider,"expected_revision":0});
    assert_eq!(
        request(&directory, "reader", std::slice::from_ref(&save))[0]["error"]["code"],
        "FORBIDDEN"
    );
    assert_eq!(
        request(&directory, "editor", &[save])[0]["result"]["revision"],
        1
    );
    let responses = request(
        &directory,
        "reader",
        &[
            json!({"op":"list_providers"}),
            json!({"op":"get_provider","id":"openrouter"}),
        ],
    );
    assert_eq!(responses[0]["result"][0]["adapter"], "openrouter");
    assert_eq!(
        responses[1]["result"]["credential_ref"],
        "env:OPENROUTER_API_KEY"
    );
}
