use super::*;
use std::collections::{BTreeMap, BTreeSet};

pub(crate) fn identifier(id: &str) -> Result<()> {
    if id.is_empty()
        || id.len() > 128
        || !id.as_bytes()[0].is_ascii_alphanumeric()
        || !id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err(Error::invalid(format!(
            "Invalid identifier {id:?}; use letters, digits, '-' or '_', starting with a letter or digit"
        )));
    }
    Ok(())
}

fn unique(values: &[String], what: &str) -> Result<()> {
    let distinct: BTreeSet<_> = values.iter().collect();
    if distinct.len() != values.len() || values.iter().any(|v| v.trim().is_empty()) {
        return Err(Error::invalid(format!(
            "{what} must be non-empty and unique"
        )));
    }
    Ok(())
}

pub(crate) fn validate(config: &Configuration) -> Result<()> {
    for (id, provider) in &config.providers {
        provider.validate()?;
        if id != &provider.id {
            return Err(Error::invalid("Provider map keys must match provider IDs"));
        }
    }
    for (id, template) in &config.prompts {
        identifier(id)?;
        if id != &template.id {
            return Err(Error::invalid("Prompt map keys must match prompt IDs"));
        }
        prompt::validate(template)?;
    }
    for (id, profile) in &config.profiles {
        identifier(id)?;
        if id != &profile.id {
            return Err(Error::invalid("Profile map keys must match profile IDs"));
        }
        unique(&profile.prompt_ids, "Prompt references")?;
        unique(&profile.tools, "Tool references")?;
        if let Some(provider) = &profile.provider_id {
            if !config.providers.contains_key(provider) {
                return Err(Error::invalid(format!(
                    "Profile {id} references missing provider {provider}"
                )));
            }
            if profile.model.is_none() || profile.credential_ref.is_some() {
                return Err(Error::invalid(
                    "Connected profiles require a model; store credentials on the provider",
                ));
            }
        }
        for prompt in &profile.prompt_ids {
            if !config.prompts.contains_key(prompt) {
                return Err(Error::invalid(format!(
                    "Profile {id} references missing prompt {prompt}"
                )));
            }
        }
        if matches!(
            profile.component,
            Component::Agent | Component::Orchestrator
        ) && (profile.prompt_ids.is_empty()
            || profile
                .model
                .as_ref()
                .is_none_or(|model| model.trim().is_empty()))
        {
            return Err(Error::invalid(format!(
                "LLM profile {id} requires a model and at least one prompt"
            )));
        }
        if profile.model.as_ref().is_some_and(|v| v.trim().is_empty())
            || profile
                .credential_ref
                .as_ref()
                .is_some_and(|v| v.trim().is_empty())
        {
            return Err(Error::invalid(format!(
                "Profile {id} has an empty model or credential reference"
            )));
        }
        for (key, value) in &profile.settings {
            if key.trim().is_empty() {
                return Err(Error::invalid("Setting names must not be empty"));
            }
            if matches!(
                key.as_str(),
                "token_budget"
                    | "context_budget_tokens"
                    | "max_tool_calls"
                    | "timeout_ms"
                    | "max_search_results"
                    | "max_step_executions"
                    | "max_output_tokens"
            ) && value.as_u64().is_none_or(|v| v == 0)
            {
                return Err(Error::invalid(format!(
                    "Profile {id}: {key} must be a positive integer"
                )));
            }
            if matches!(key.as_str(), "checkpoint_after_tools" | "exclude_ignored")
                && !value.is_boolean()
            {
                return Err(Error::invalid(format!(
                    "Profile {id}: {key} must be a boolean"
                )));
            }
        }
        for (key, maximum) in [("temperature", 2.0), ("top_p", 1.0)] {
            if profile.settings.get(key).is_some_and(|v| {
                v.as_f64()
                    .is_none_or(|n| !n.is_finite() || n < 0.0 || n > maximum)
            }) {
                return Err(Error::invalid(format!("Profile {id}: invalid {key}")));
            }
        }
    }
    for (id, workflow) in &config.workflows {
        identifier(id)?;
        if id != &workflow.id {
            return Err(Error::invalid("Workflow map keys must match workflow IDs"));
        }
        validate_workflow(workflow, config)?;
    }
    Ok(())
}

/// HTTPS connections, with HTTP allowed only for local development servers.
pub(crate) fn validate_base_url(url: &str) -> Result<()> {
    let (scheme, rest) = url
        .split_once("://")
        .ok_or_else(|| Error::invalid("API base URL needs a scheme"))?;
    let authority = rest.split('/').next().unwrap_or("");
    if authority.is_empty()
        || url.chars().any(|c| c.is_whitespace() || c.is_control())
        || url.contains(['?', '#', '@', '\\'])
    {
        return Err(Error::invalid(
            "API base URL must have a host and no credentials, query, or fragment",
        ));
    }
    let host = if authority.starts_with('[') {
        authority
            .split_once(']')
            .map(|(h, _)| format!("{h}]"))
            .unwrap_or_default()
    } else {
        authority.split(':').next().unwrap_or("").to_string()
    };
    if scheme != "https"
        && !(scheme == "http" && matches!(host.as_str(), "localhost" | "127.0.0.1" | "[::1]"))
    {
        return Err(Error::invalid(
            "API connections require HTTPS; HTTP is allowed on loopback only",
        ));
    }
    Ok(())
}

fn validate_workflow(workflow: &Workflow, config: &Configuration) -> Result<()> {
    if workflow.max_step_executions == 0 {
        return Err(Error::invalid(
            "Workflow max_step_executions must be positive",
        ));
    }
    if !workflow.steps.contains_key(&workflow.start) {
        return Err(Error::invalid(format!(
            "Workflow {} has no start step {}",
            workflow.id, workflow.start
        )));
    }
    let mut reverse: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut terminal_reachable = BTreeSet::new();
    for (name, step) in &workflow.steps {
        identifier(name)?;
        let agent = config.profiles.get(&step.agent_profile).ok_or_else(|| {
            Error::invalid(format!(
                "Step {name} references missing profile {}",
                step.agent_profile
            ))
        })?;
        if agent.component != Component::Agent {
            return Err(Error::invalid(format!(
                "Step {name} must reference an agent profile"
            )));
        }
        unique(&step.inputs, "Step inputs")?;
        if step
            .inputs
            .iter()
            .any(|input| !prompt::valid_variable(input))
        {
            return Err(Error::invalid(format!(
                "Step {name} has an invalid input name"
            )));
        }
        for required in agent
            .prompt_ids
            .iter()
            .flat_map(|id| &config.prompts[id].variables)
        {
            if !step.inputs.contains(required) {
                return Err(Error::invalid(format!(
                    "Step {name} does not provide prompt input {required}"
                )));
            }
        }
        if step.transitions.is_empty() {
            return Err(Error::invalid(format!(
                "Step {name} needs at least one transition"
            )));
        }
        for (outcome, target) in &step.transitions {
            identifier(outcome)?;
            match target {
                Transition::Step { step: target } => {
                    if !workflow.steps.contains_key(target) {
                        return Err(Error::invalid(format!(
                            "Step {name} transitions to unknown step {target}"
                        )));
                    }
                    reverse
                        .entry(target.clone())
                        .or_default()
                        .push(name.clone());
                }
                _ => {
                    terminal_reachable.insert(name.clone());
                }
            }
        }
    }
    let mut pending: Vec<_> = terminal_reachable.iter().cloned().collect();
    while let Some(name) = pending.pop() {
        for previous in reverse.get(&name).into_iter().flatten() {
            if terminal_reachable.insert(previous.clone()) {
                pending.push(previous.clone());
            }
        }
    }
    if terminal_reachable.len() != workflow.steps.len() {
        return Err(Error::invalid(
            "Every workflow step must have a path to a terminal outcome",
        ));
    }
    let mut reachable = BTreeSet::new();
    let mut pending = vec![workflow.start.clone()];
    while let Some(name) = pending.pop() {
        if reachable.insert(name.clone()) {
            pending.extend(
                workflow.steps[&name]
                    .transitions
                    .values()
                    .filter_map(|target| match target {
                        Transition::Step { step } => Some(step.clone()),
                        _ => None,
                    }),
            );
        }
    }
    if reachable.len() != workflow.steps.len() {
        return Err(Error::invalid(
            "Workflow contains steps unreachable from its start",
        ));
    }
    Ok(())
}
