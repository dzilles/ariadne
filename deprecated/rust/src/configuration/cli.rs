use super::*;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    io::{self, BufRead, Write},
    path::PathBuf,
};

#[derive(Clone, Copy, PartialEq, Eq)]
enum Role {
    Reader,
    Editor,
}

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Request {
    ListProviders,
    GetProvider {
        id: String,
    },
    SaveProvider {
        provider: Provider,
        expected_revision: Option<u64>,
    },
    ListProfiles {
        component: Option<Component>,
    },
    GetProfile {
        id: String,
    },
    GetPrompt {
        id: String,
    },
    GetWorkflow {
        id: String,
    },
    ListWorkflows,
    Validate,
    SavePrompt {
        id: String,
        text: String,
        #[serde(default)]
        variables: Vec<String>,
        expected_revision: Option<u64>,
    },
    SaveProfile {
        profile: Profile,
        expected_revision: Option<u64>,
    },
    SaveWorkflow {
        definition: Workflow,
        expected_revision: Option<u64>,
    },
    ReplaceConfiguration {
        configuration: Configuration,
        expected_revision: Option<u64>,
    },
    CreateSnapshot,
    GetSnapshot {
        id: String,
    },
    RenderProfile {
        id: String,
        #[serde(default)]
        variables: BTreeMap<String, String>,
        snapshot_id: Option<String>,
    },
}

fn execute(store: &ConfigurationStore, role: Role, request: Request) -> Result<Value> {
    if role != Role::Editor
        && matches!(
            request,
            Request::SavePrompt { .. }
                | Request::SaveProvider { .. }
                | Request::SaveProfile { .. }
                | Request::SaveWorkflow { .. }
                | Request::ReplaceConfiguration { .. }
        )
    {
        return Err(Error::new(
            "FORBIDDEN",
            "Configuration edits require --role editor",
        ));
    }
    Ok(match request {
        Request::ListProviders => serde_json::to_value(store.list_providers()?)?,
        Request::GetProvider { id } => serde_json::to_value(store.get_provider(&id)?)?,
        Request::SaveProvider {
            provider,
            expected_revision,
        } => json!({"revision":store.save_provider(provider, expected_revision)?}),
        Request::ListProfiles { component } => {
            serde_json::to_value(store.list_profiles(component)?)?
        }
        Request::GetProfile { id } => serde_json::to_value(store.get_profile(&id)?)?,
        Request::GetPrompt { id } => serde_json::to_value(store.get_prompt(&id)?)?,
        Request::GetWorkflow { id } => serde_json::to_value(store.get_workflow(&id)?)?,
        Request::ListWorkflows => serde_json::to_value(store.list_workflows()?)?,
        Request::Validate => serde_json::to_value(store.status()?)?,
        Request::SavePrompt {
            id,
            text,
            variables,
            expected_revision,
        } => {
            json!({"revision":store.save_prompt(Prompt { id, text, variables }, expected_revision)?})
        }
        Request::SaveProfile {
            profile,
            expected_revision,
        } => json!({"revision":store.save_profile(profile, expected_revision)?}),
        Request::SaveWorkflow {
            definition,
            expected_revision,
        } => json!({"revision":store.save_workflow(definition, expected_revision)?}),
        Request::ReplaceConfiguration {
            configuration,
            expected_revision,
        } => json!({"revision":store.replace_configuration(configuration, expected_revision)?}),
        Request::CreateSnapshot => {
            let snapshot = store.create_snapshot()?;
            json!({"id":snapshot.id,"revision":snapshot.revision})
        }
        Request::GetSnapshot { id } => serde_json::to_value(store.get_snapshot(&id)?)?,
        Request::RenderProfile {
            id,
            variables,
            snapshot_id,
        } => {
            if let Some(snapshot_id) = snapshot_id {
                let snapshot = store.get_snapshot(&snapshot_id)?;
                json!({"snapshot_id":snapshot.id,"revision":snapshot.revision,"resolved":snapshot.render_profile(&id, &variables)?})
            } else {
                let (revision, config) = store.load()?;
                json!({"snapshot_id":null,"revision":revision,"resolved":config.render_profile(&id, &variables)?})
            }
        }
    })
}

/// Entry point for `ariadne-tasks config ...`; the root binary selects the module.
pub fn run() -> Result<()> {
    let mut root = PathBuf::from(".ariadne");
    let mut role = Role::Reader;
    let mut arguments = std::env::args().skip(2);
    while let Some(argument) = arguments.next() {
        match argument.as_str() {
            "--root" => {
                root = arguments
                    .next()
                    .map(PathBuf::from)
                    .ok_or_else(|| Error::invalid("--root needs a directory"))?
            }
            "--role" => {
                role = match arguments.next().as_deref() {
                    Some("reader") => Role::Reader,
                    Some("editor") => Role::Editor,
                    _ => return Err(Error::invalid("--role must be reader or editor")),
                }
            }
            "--tools" => {
                println!("{}", serde_json::to_string_pretty(&tool_definitions())?);
                return Ok(());
            }
            "--help" | "-h" => {
                println!(
                    "ariadne-tasks config [--root DIR] [--role reader|editor]\nRead one JSON request per line; emit one JSON response per line.\nDefault directory: .ariadne. Default role: reader.\n--tools prints read-only profile/workflow discovery tool schemas."
                );
                return Ok(());
            }
            _ => {
                return Err(Error::invalid(format!(
                    "Unknown argument {argument}; use config --help"
                )));
            }
        }
    }
    let store = ConfigurationStore::open(root)?;
    let mut output = io::BufWriter::new(io::stdout().lock());
    for line in io::stdin().lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let result = serde_json::from_str(&line)
            .map_err(Error::from)
            .and_then(|request| execute(&store, role, request));
        let response = match result {
            Ok(result) => json!({"ok":true,"result":result}),
            Err(error) => json!({"ok":false,"error":error}),
        };
        writeln!(output, "{}", serde_json::to_string(&response)?)?;
        output.flush()?;
    }
    Ok(())
}

pub fn tool_definitions() -> Vec<Value> {
    vec![
        json!({"name":"list_profiles","description":"Discover configured component profiles, including agent purpose, model, and tool IDs. Does not change configuration.","input_schema":{
            "type":"object","additionalProperties":false,"properties":{"component":{"type":"string","enum":["agent","orchestrator","context_service","runtime","git_tracker","workflow_engine","tool"]}}
        }}),
        json!({"name":"get_profile","description":"Inspect an existing component profile by ID. Credentials are references, not resolved secrets.","input_schema":{
            "type":"object","additionalProperties":false,"properties":{"id":{"type":"string"}},"required":["id"]
        }}),
        json!({"name":"list_workflows","description":"Discover configured workflows and their agent steps. Does not execute them.","input_schema":{
            "type":"object","additionalProperties":false,"properties":{}
        }}),
        json!({"name":"get_workflow","description":"Read a configured workflow by ID, including transitions and execution limits.","input_schema":{
            "type":"object","additionalProperties":false,"properties":{"id":{"type":"string"}},"required":["id"]
        }}),
    ]
}
