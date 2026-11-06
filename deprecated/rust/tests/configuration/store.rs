use super::support::*;
use ariadne_tasks::configuration::*;
use serde_json::{Value, json};
use std::fs::{self, OpenOptions};

#[test]
fn profiles_prompts_and_workflows_roundtrip_through_files() {
    let directory = Directory::new();
    let store = directory.store();
    assert_eq!(store.status().unwrap().revision, 0);
    let config = configuration();
    assert_eq!(
        store
            .replace_configuration(config.clone(), Some(0))
            .unwrap(),
        1
    );
    let reopened = directory.store();
    assert_eq!(reopened.load().unwrap(), (1, config.clone()));
    assert_eq!(
        reopened
            .list_profiles(Some(Component::Agent))
            .unwrap()
            .len(),
        3
    );
    assert_eq!(reopened.list_profiles(None).unwrap().len(), 8);
    assert_eq!(reopened.list_workflows().unwrap().len(), 1);
    assert_eq!(
        reopened
            .get_workflow("code-review-test")
            .unwrap()
            .max_step_executions,
        12
    );
    assert_eq!(
        reopened
            .get_profile("coder")
            .unwrap()
            .provider_id
            .as_deref(),
        Some("openrouter")
    );
    assert_eq!(
        reopened.get_prompt("missing").unwrap_err().code,
        "NOT_FOUND"
    );
    let manifest: Value =
        serde_json::from_slice(&fs::read(directory.0.join("config.json")).unwrap()).unwrap();
    let file = manifest["prompts"]["coder"]["file"].as_str().unwrap();
    assert!(file.ends_with(".md"));
    assert_eq!(
        fs::read_to_string(directory.0.join(file)).unwrap(),
        config.prompts["coder"].text
    );
}

#[test]
fn individual_save_operations_and_revision_checks_work() {
    let directory = Directory::new();
    let store = directory.store();
    let config = configuration();
    for provider in config.providers.values() {
        store.save_provider(provider.clone(), None).unwrap();
    }
    for prompt in config.prompts.values() {
        store.save_prompt(prompt.clone(), None).unwrap();
    }
    for profile in config.profiles.values() {
        store.save_profile(profile.clone(), None).unwrap();
    }
    store
        .save_workflow(config.workflows["code-review-test"].clone(), None)
        .unwrap();
    let revision = store.status().unwrap().revision;
    let another = directory.store();
    let mut coder = store.get_profile("coder").unwrap();
    coder.settings.insert("timeout_ms".into(), json!(12345));
    assert_eq!(
        store.save_profile(coder.clone(), Some(revision)).unwrap(),
        revision + 1
    );
    let mut tester = another.get_profile("tester").unwrap();
    tester.description = "Updated tester role".into();
    assert_eq!(
        another
            .save_profile(tester.clone(), Some(revision))
            .unwrap_err()
            .code,
        "VERSION_CONFLICT"
    );
    another.save_profile(tester, None).unwrap();
    assert_eq!(
        store.get_profile("coder").unwrap().settings["timeout_ms"],
        12345
    );
    assert_eq!(
        store.get_profile("tester").unwrap().description,
        "Updated tester role"
    );
}

#[test]
fn snapshots_keep_resolved_text_after_edits_restart_and_old_file_removal() {
    let directory = Directory::new();
    let store = directory.store();
    store.replace_configuration(configuration(), None).unwrap();
    let snapshot = store.create_snapshot().unwrap();
    let old_text = snapshot
        .render_profile("coder", &coder_inputs())
        .unwrap()
        .prompts[0]
        .text
        .clone();
    let old_manifest: Value =
        serde_json::from_slice(&fs::read(directory.0.join("config.json")).unwrap()).unwrap();
    let mut prompt = store.get_prompt("coder").unwrap();
    prompt.text.push_str("\nNew instruction for future runs.");
    store.save_prompt(prompt, Some(1)).unwrap();
    assert!(
        store
            .load()
            .unwrap()
            .1
            .render_profile("coder", &coder_inputs())
            .unwrap()
            .prompts[0]
            .text
            .contains("New instruction")
    );
    fs::remove_file(
        directory
            .0
            .join(old_manifest["prompts"]["coder"]["file"].as_str().unwrap()),
    )
    .unwrap();
    let reopened = directory.store();
    let saved = reopened.get_snapshot(&snapshot.id).unwrap();
    assert_eq!(saved, snapshot);
    assert_eq!(
        saved
            .render_profile("coder", &coder_inputs())
            .unwrap()
            .prompts[0]
            .text,
        old_text
    );
    assert_eq!(saved.revision, 1);
    assert_eq!(reopened.status().unwrap().revision, 2);
    assert!(reopened.get_snapshot("../outside").is_err());
}

#[test]
fn invalid_coordinated_edits_do_not_publish_any_files() {
    let directory = Directory::new();
    let store = directory.store();
    store.replace_configuration(configuration(), None).unwrap();
    let before = fs::read(directory.0.join("config.json")).unwrap();
    let files_before = fs::read_dir(directory.0.join("prompts")).unwrap().count();
    let mut config = configuration();
    config
        .prompts
        .get_mut("coder")
        .unwrap()
        .text
        .push_str("\n{{missing_input}}");
    assert!(store.replace_configuration(config, Some(1)).is_err());
    assert_eq!(fs::read(directory.0.join("config.json")).unwrap(), before);
    assert_eq!(
        fs::read_dir(directory.0.join("prompts")).unwrap().count(),
        files_before
    );
    // The failed save released its lock and left the old configuration usable.
    let mut profile = store.get_profile("coder").unwrap();
    profile.description = "Still editable".into();
    assert_eq!(store.save_profile(profile, Some(1)).unwrap(), 2);
}

#[test]
fn writer_lock_prevents_lost_updates_without_a_stale_lock_file() {
    let directory = Directory::new();
    let store = directory.store();
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .open(directory.0.join(".write.lock"))
        .unwrap();
    lock.try_lock().unwrap();
    assert_eq!(
        store
            .replace_configuration(configuration(), None)
            .unwrap_err()
            .code,
        "CONFIGURATION_BUSY"
    );
    lock.unlock().unwrap();
    drop(lock);
    assert_eq!(
        store
            .replace_configuration(configuration(), Some(0))
            .unwrap(),
        1
    );
}

#[test]
fn prompt_locations_cannot_escape_the_configuration_directory() {
    let directory = Directory::new();
    let store = directory.store();
    store.replace_configuration(configuration(), None).unwrap();
    let path = directory.0.join("config.json");
    let mut manifest: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    manifest["prompts"]["coder"]["file"] = json!("prompts/../../outside.md");
    fs::write(path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    assert_eq!(store.load().unwrap_err().code, "VALIDATION_ERROR");
}

#[test]
fn coordinated_prompt_and_workflow_changes_can_be_published_together() {
    let directory = Directory::new();
    let store = directory.store();
    store.replace_configuration(configuration(), None).unwrap();
    let mut updated = configuration();
    let prompt = updated.prompts.get_mut("coder").unwrap();
    prompt
        .text
        .push_str("\nNew requirement: {{acceptance_criteria}}");
    prompt.variables.push("acceptance_criteria".into());
    assert!(store.save_prompt(prompt.clone(), Some(1)).is_err());
    updated
        .workflows
        .get_mut("code-review-test")
        .unwrap()
        .steps
        .get_mut("code")
        .unwrap()
        .inputs
        .push("acceptance_criteria".into());
    assert_eq!(store.replace_configuration(updated, Some(1)).unwrap(), 2);
}
