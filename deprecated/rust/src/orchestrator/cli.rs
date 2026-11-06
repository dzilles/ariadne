use super::*;
use crate::{
    Error, Result,
    configuration::{Component, Configuration, ConfigurationStore, Profile, Prompt, Provider},
    llm::Gateway,
};
use serde_json::json;
use std::{collections::BTreeMap, path::Path, sync::Arc};

pub fn initialize(root: &Path, model: &str) -> Result<()> {
    if model.trim().is_empty() {
        return Err(Error::invalid("Choose an OpenRouter model ID with --model"));
    }
    let store = ConfigurationStore::open(root)?;
    let prompt=Prompt{id:"orchestrator".into(),text:"You are Ariadne, a project orchestrator. Help the user plan work, create and inspect tasks, refine acceptance criteria, and understand progress. Use tools when the request needs stored facts.\n\nActive project: {{project_id}}\nProject summary: {{project_summary}}".into(),variables:vec!["project_id".into(),"project_summary".into()]};
    let mut catalog = crate::task::tools::tool_definitions();
    catalog.extend(crate::configuration::cli::tool_definitions());
    let config = Configuration {
        providers: BTreeMap::from([(
            "openrouter".into(),
            Provider {
                id: "openrouter".into(),
                adapter: "openrouter".into(),
                base_url: "https://openrouter.ai/api/v1".into(),
                credential_ref: "env:OPENROUTER_API_KEY".into(),
            },
        )]),
        prompts: BTreeMap::from([("orchestrator".into(), prompt)]),
        profiles: BTreeMap::from([(
            "orchestrator".into(),
            Profile {
                id: "orchestrator".into(),
                description: "Coordinate project work and tasks".into(),
                component: Component::Orchestrator,
                prompt_ids: vec!["orchestrator".into()],
                model: Some(model.into()),
                provider_id: Some("openrouter".into()),
                credential_ref: None,
                tools: catalog
                    .iter()
                    .map(|tool| tool["name"].as_str().unwrap().into())
                    .collect(),
                settings: BTreeMap::from([
                    ("max_tool_calls".into(), json!(12)),
                    ("max_output_tokens".into(), json!(2048)),
                    ("timeout_ms".into(), json!(120000)),
                ]),
            },
        )]),
        workflows: BTreeMap::new(),
    };
    store.replace_configuration(config, Some(0))?;
    Ok(())
}

pub fn run() -> Result<()> {
    let mut options = Options::default();
    let mut port = 8787;
    let mut terminal = false;
    let mut init = false;
    let mut model = None;
    let mut args = std::env::args().skip(2);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "init" => init = true,
            "--root" => {
                options.root = args
                    .next()
                    .ok_or_else(|| Error::invalid("--root needs a path"))?
                    .into()
            }
            "--db" => {
                options.task_path = args
                    .next()
                    .ok_or_else(|| Error::invalid("--db needs a path"))?
                    .into()
            }
            "--project" => {
                options.project_id = args
                    .next()
                    .ok_or_else(|| Error::invalid("--project needs an ID"))?
            }
            "--profile" => {
                options.profile_id = args
                    .next()
                    .ok_or_else(|| Error::invalid("--profile needs an ID"))?
            }
            "--project-summary" => {
                options.project_summary = args
                    .next()
                    .ok_or_else(|| Error::invalid("--project-summary needs text"))?
            }
            "--port" => {
                port = args
                    .next()
                    .and_then(|p| p.parse::<u16>().ok())
                    .ok_or_else(|| Error::invalid("--port needs a number"))?
            }
            "--terminal" => terminal = true,
            "--model" => model = args.next(),
            "--help" | "-h" => {
                println!(
                    "ariadne-tasks chat init --model MODEL [--root DIR]\nariadne-tasks chat [--root DIR] [--db PATH] [--project ID] [--profile ID] [--port 8787] [--terminal]\nSet OPENROUTER_API_KEY in the environment before chatting.\nDefault UI: http://127.0.0.1:8787. Existing configuration is never overwritten by init."
                );
                return Ok(());
            }
            _ => return Err(Error::invalid(format!("Unknown chat option {arg}"))),
        }
    }
    if init {
        initialize(
            &options.root,
            &model.ok_or_else(|| Error::invalid("chat init requires --model MODEL"))?,
        )?;
        println!(
            "Saved OpenRouter configuration in {}",
            options.root.display()
        );
        return Ok(());
    }
    if model.is_some() {
        return Err(Error::invalid(
            "Set model choices in configuration; --model is only for chat init",
        ));
    }
    let app = Application::start(options, Arc::new(Gateway::default()))?;
    if terminal {
        crate::ui::terminal(app)
    } else {
        crate::ui::serve(app, port)
    }
}
