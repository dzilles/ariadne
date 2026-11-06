use super::support::*;
use ariadne_tasks::configuration::*;
use serde_json::json;
use std::collections::{BTreeMap, BTreeSet};

#[test]
fn rejects_missing_prompts_profiles_and_transition_targets() {
    let mut config = configuration();
    config
        .profiles
        .get_mut("coder")
        .unwrap()
        .prompt_ids
        .push("missing".into());
    assert!(config.validate().is_err());
    let mut config = configuration();
    config
        .workflows
        .get_mut("code-review-test")
        .unwrap()
        .steps
        .get_mut("code")
        .unwrap()
        .agent_profile = "missing".into();
    assert!(config.validate().is_err());
    let mut config = configuration();
    config
        .workflows
        .get_mut("code-review-test")
        .unwrap()
        .steps
        .get_mut("code")
        .unwrap()
        .transitions
        .insert(
            "completed".into(),
            Transition::Step {
                step: "missing".into(),
            },
        );
    assert!(config.validate().is_err());
}

#[test]
fn rejects_wrong_component_invalid_settings_and_duplicate_tool_ids() {
    let mut config = configuration();
    config.profiles.get_mut("coder").unwrap().component = Component::Runtime;
    assert!(config.validate().is_err());
    for value in [json!(0), json!(-1), json!("large"), json!(1.5)] {
        let mut config = configuration();
        config
            .profiles
            .get_mut("coder")
            .unwrap()
            .settings
            .insert("token_budget".into(), value);
        assert!(config.validate().is_err());
    }
    let mut config = configuration();
    config
        .profiles
        .get_mut("coder")
        .unwrap()
        .tools
        .push("read_file".into());
    assert!(config.validate().is_err());
    let mut config = configuration();
    config.profiles.get_mut("orchestrator").unwrap().model = None;
    assert!(config.validate().is_err());
}

#[test]
fn bounded_review_loops_are_valid_but_unreachable_or_nonterminating_graphs_are_not() {
    assert!(configuration().validate().is_ok());
    let mut config = configuration();
    config
        .workflows
        .get_mut("code-review-test")
        .unwrap()
        .max_step_executions = 0;
    assert!(config.validate().is_err());
    let mut config = configuration();
    let workflow = config.workflows.get_mut("code-review-test").unwrap();
    for (name, step) in &mut workflow.steps {
        step.transitions =
            BTreeMap::from([("repeat".into(), Transition::Step { step: name.clone() })]);
    }
    assert!(config.validate().is_err());
    let mut config = configuration();
    let workflow = config.workflows.get_mut("code-review-test").unwrap();
    workflow
        .steps
        .insert("unreachable".into(), workflow.steps["test"].clone());
    assert!(config.validate().is_err());
}

#[test]
fn prompt_inputs_are_checked_and_values_are_never_reinterpreted_as_templates() {
    let config = configuration();
    assert!(config.render_profile("coder", &BTreeMap::new()).is_err());
    let mut values = coder_inputs();
    values.insert("typo".into(), "wrong".into());
    assert!(config.render_profile("coder", &values).is_err());
    let mut config = configuration();
    let prompt = config.prompts.get_mut("coder").unwrap();
    prompt.text = "Задача: {{ task }}.".into();
    prompt.variables = vec!["task".into()];
    let resolved = config
        .render_profile(
            "coder",
            &BTreeMap::from([("task".into(), "Keep {{project_context}} literally".into())]),
        )
        .unwrap();
    assert_eq!(
        resolved.prompts[0].text,
        "Задача: Keep {{project_context}} literally."
    );
    let mut config = configuration();
    config
        .prompts
        .get_mut("coder")
        .unwrap()
        .text
        .push_str("{{unclosed");
    assert!(config.validate().is_err());
    let mut config = configuration();
    config
        .workflows
        .get_mut("code-review-test")
        .unwrap()
        .steps
        .get_mut("code")
        .unwrap()
        .inputs
        .clear();
    assert!(config.validate().is_err());
}

#[test]
fn configuration_can_be_checked_against_the_actual_runtime_tool_registry() {
    let config = configuration();
    let available: BTreeSet<_> = config
        .profiles
        .values()
        .flat_map(|profile| profile.tools.iter().cloned())
        .collect();
    assert!(
        config
            .validate_tools(&available.into_iter().collect::<Vec<_>>())
            .is_ok()
    );
    assert!(config.validate_tools(&["read_file".into()]).is_err());
}

#[test]
fn ids_and_unknown_fields_are_validated_before_files_are_written() {
    let mut config = configuration();
    let prompt = config.prompts.remove("coder").unwrap();
    config.prompts.insert("../outside".into(), prompt);
    assert!(config.validate().is_err());
    let bad = json!({"id":"profile","component":"runtime","api_key":"not-a-supported-field"});
    assert!(serde_json::from_value::<Profile>(bad).is_err());
}
