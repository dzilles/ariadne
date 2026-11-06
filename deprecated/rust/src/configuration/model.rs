use super::*;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Component {
    Orchestrator,
    Agent,
    ContextService,
    Runtime,
    GitTracker,
    WorkflowEngine,
    Tool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Provider {
    pub id: String,
    pub adapter: String,
    pub base_url: String,
    pub credential_ref: String,
}
impl Provider {
    pub fn validate(&self) -> Result<()> {
        validation::identifier(&self.id)?;
        validation::identifier(&self.adapter)?;
        validation::validate_base_url(&self.base_url)?;
        let name = self
            .credential_ref
            .strip_prefix("env:")
            .ok_or_else(|| Error::invalid("Credentials must reference env:NAME"))?;
        if !prompt::valid_variable(name) {
            return Err(Error::invalid(
                "Invalid credential environment variable name",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Prompt {
    pub id: String,
    pub text: String,
    #[serde(default)]
    pub variables: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    pub id: String,
    #[serde(default)]
    pub description: String,
    pub component: Component,
    #[serde(default)]
    pub prompt_ids: Vec<String>,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provider_id: Option<String>,
    /// Legacy manifests remain readable. New profiles use provider credentials.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub credential_ref: Option<String>,
    #[serde(default)]
    pub tools: Vec<String>,
    #[serde(default)]
    pub settings: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Workflow {
    pub id: String,
    pub start: String,
    #[serde(default = "default_step_limit")]
    pub max_step_executions: u32,
    pub steps: BTreeMap<String, Step>,
}
fn default_step_limit() -> u32 {
    12
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Step {
    pub agent_profile: String,
    #[serde(default)]
    pub inputs: Vec<String>,
    pub transitions: BTreeMap<String, Transition>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Transition {
    Step { step: String },
    Completed,
    Blocked,
    Cancelled,
    Failed,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Configuration {
    #[serde(default)]
    pub providers: BTreeMap<String, Provider>,
    #[serde(default)]
    pub prompts: BTreeMap<String, Prompt>,
    #[serde(default)]
    pub profiles: BTreeMap<String, Profile>,
    #[serde(default)]
    pub workflows: BTreeMap<String, Workflow>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub id: String,
    pub revision: u64,
    pub configuration: Configuration,
}

#[derive(Debug, Clone, Serialize)]
pub struct ConfigurationStatus {
    pub revision: u64,
    pub providers: usize,
    pub profiles: usize,
    pub prompts: usize,
    pub workflows: usize,
}
#[derive(Debug, Clone, Serialize)]
pub struct RenderedPrompt {
    pub id: String,
    pub text: String,
}
#[derive(Debug, Clone, Serialize)]
pub struct ResolvedProfile {
    pub profile: Profile,
    pub prompts: Vec<RenderedPrompt>,
}

impl Configuration {
    pub fn validate(&self) -> Result<()> {
        validation::validate(self)
    }

    /// Validates selected tool IDs against a future runtime's real registry.
    pub fn validate_tools(&self, available: &[String]) -> Result<()> {
        for profile in self.profiles.values() {
            for tool in &profile.tools {
                if !available.contains(tool) {
                    return Err(Error::invalid(format!(
                        "Profile {} references unavailable tool {tool}",
                        profile.id
                    )));
                }
            }
        }
        Ok(())
    }

    pub fn render_profile(
        &self,
        id: &str,
        values: &BTreeMap<String, String>,
    ) -> Result<ResolvedProfile> {
        self.validate()?;
        let profile = self
            .profiles
            .get(id)
            .ok_or_else(|| Error::new("NOT_FOUND", format!("Profile {id} does not exist")))?;
        let required: std::collections::BTreeSet<_> = profile
            .prompt_ids
            .iter()
            .flat_map(|id| self.prompts[id].variables.iter().cloned())
            .collect();
        for key in values.keys() {
            if !required.contains(key) {
                return Err(Error::invalid(format!(
                    "Unexpected prompt input {key} for profile {id}"
                )));
            }
        }
        let mut prompts = Vec::new();
        for prompt_id in &profile.prompt_ids {
            let prompt = &self.prompts[prompt_id];
            prompts.push(RenderedPrompt {
                id: prompt_id.clone(),
                text: prompt::render(prompt, values)?,
            });
        }
        Ok(ResolvedProfile {
            profile: profile.clone(),
            prompts,
        })
    }
}

impl Snapshot {
    pub fn render_profile(
        &self,
        id: &str,
        values: &BTreeMap<String, String>,
    ) -> Result<ResolvedProfile> {
        self.configuration.render_profile(id, values)
    }
}
