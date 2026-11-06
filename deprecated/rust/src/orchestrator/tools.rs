use crate::{
    Error, Result,
    configuration::{Component, Configuration},
    llm::ToolDefinition,
    task::{self, DemoEmbedder, TaskStore},
};
use serde::Deserialize;
use serde_json::{Value, json};

pub struct TaskTools<'a> {
    pub store: &'a mut TaskStore,
    pub configuration: &'a Configuration,
    pub project_id: &'a str,
    pub profile_id: &'a str,
}
impl TaskTools<'_> {
    pub fn definitions(config: &Configuration, profile_id: &str) -> Result<Vec<ToolDefinition>> {
        let profile = config
            .profiles
            .get(profile_id)
            .ok_or_else(|| Error::new("NOT_FOUND", "Orchestrator profile does not exist"))?;
        let mut catalog = task::tools::tool_definitions();
        catalog.extend(crate::configuration::cli::tool_definitions());
        let mut selected = Vec::new();
        for name in &profile.tools {
            let mut tool = catalog
                .iter()
                .find(|tool| tool["name"] == *name)
                .cloned()
                .ok_or_else(|| {
                    Error::invalid(format!("Orchestrator tool {name} is unavailable"))
                })?;
            if let Some(properties) = tool["input_schema"]["properties"].as_object_mut() {
                properties.remove("project_id");
            }
            if let Some(required) = tool["input_schema"]["required"].as_array_mut() {
                required.retain(|name| name != "project_id");
            }
            selected.push(serde_json::from_value(tool)?);
        }
        Ok(selected)
    }
    pub fn call(&mut self, name: &str, arguments: Value) -> Result<Value> {
        let allowed = Self::definitions(self.configuration, self.profile_id)?;
        if !allowed.iter().any(|tool| tool.name == name) {
            return Err(Error::new(
                "FORBIDDEN",
                "Tool is not enabled for this profile",
            ));
        }
        let mut args = arguments
            .as_object()
            .cloned()
            .ok_or_else(|| Error::invalid("Tool arguments must be an object"))?;
        if args.contains_key("project_id") || args.contains_key("op") {
            return Err(Error::invalid(
                "Project and operation are supplied by the application",
            ));
        }
        if task::tools::tool_definitions()
            .iter()
            .any(|tool| tool["name"] == name)
        {
            let id_field = match name {
                "get_task" | "update_task" | "get_history" => Some("id"),
                "annotate_reference" | "add_note" => Some("task_id"),
                _ => None,
            };
            if let Some(field) = id_field {
                let id = args
                    .get(field)
                    .and_then(Value::as_str)
                    .ok_or_else(|| Error::invalid(format!("Missing {field}")))?;
                if self.store.orchestrator().get_task(id)?.project_id != self.project_id {
                    return Err(Error::new("FORBIDDEN", "Task belongs to another project"));
                }
            }
            if matches!(name, "create_task" | "search_tasks") {
                args.insert("project_id".into(), json!(self.project_id));
            }
            if name == "search_tasks" && args.get("mode") == Some(&json!("semantic")) {
                self.store.index_pending(&DemoEmbedder, 200)?;
            }
            return Ok(task::tools::call(self.store, name, Value::Object(args))?);
        }
        args.insert("op".into(), json!(name));
        let command: Discovery = serde_json::from_value(Value::Object(args))?;
        Ok(match command {
            Discovery::ListProfiles { component } => json!(
                self.configuration
                    .profiles
                    .values()
                    .filter(|profile| component.is_none_or(|c| c == profile.component))
                    .collect::<Vec<_>>()
            ),
            Discovery::GetProfile { id } => json!(
                self.configuration
                    .profiles
                    .get(&id)
                    .ok_or_else(|| Error::new("NOT_FOUND", "Profile does not exist"))?
            ),
            Discovery::ListWorkflows => {
                json!(self.configuration.workflows.values().collect::<Vec<_>>())
            }
            Discovery::GetWorkflow { id } => json!(
                self.configuration
                    .workflows
                    .get(&id)
                    .ok_or_else(|| Error::new("NOT_FOUND", "Workflow does not exist"))?
            ),
        })
    }
}
#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Discovery {
    ListProfiles { component: Option<Component> },
    GetProfile { id: String },
    ListWorkflows,
    GetWorkflow { id: String },
}
