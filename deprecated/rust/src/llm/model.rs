use crate::{
    Error, Result,
    configuration::{Provider, Snapshot},
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};

#[derive(Debug, Clone, Default)]
pub struct Cancellation(Arc<AtomicBool>);
impl Cancellation {
    pub fn cancel(&self) {
        self.0.store(true, Ordering::SeqCst);
    }
    pub fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::SeqCst)
    }
    pub fn check(&self) -> Result<()> {
        if self.is_cancelled() {
            Err(Error::new("CANCELLED", "Model request cancelled"))
        } else {
            Ok(())
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Binding {
    pub provider: Provider,
    pub model: String,
    pub snapshot_id: String,
    pub settings: BTreeMap<String, Value>,
}
impl Binding {
    pub fn from_snapshot(snapshot: &Snapshot, profile_id: &str) -> Result<Self> {
        snapshot.configuration.validate()?;
        let profile = snapshot
            .configuration
            .profiles
            .get(profile_id)
            .ok_or_else(|| Error::new("NOT_FOUND", "LLM profile does not exist"))?;
        let provider = profile
            .provider_id
            .as_ref()
            .and_then(|id| snapshot.configuration.providers.get(id))
            .ok_or_else(|| {
                Error::invalid("Profile needs provider_id; configure an API connection first")
            })?;
        Ok(Self {
            provider: provider.clone(),
            model: profile
                .model
                .clone()
                .ok_or_else(|| Error::invalid("Profile has no model"))?,
            snapshot_id: snapshot.id.clone(),
            settings: profile.settings.clone(),
        })
    }
    pub fn timeout_ms(&self) -> u64 {
        self.settings
            .get("timeout_ms")
            .and_then(Value::as_u64)
            .unwrap_or(120_000)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CallContext {
    pub call_id: String,
    pub caller_id: String,
    pub snapshot_id: String,
    pub session_id: Option<String>,
    pub run_id: Option<String>,
    pub task_id: Option<String>,
    pub parent_call_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    System,
    User,
    Assistant,
    Tool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    /// Original JSON string is retained for provider continuation.
    pub arguments: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Message {
    pub role: Role,
    pub content: Option<String>,
    #[serde(default)]
    pub tool_calls: Vec<ToolCall>,
    pub tool_call_id: Option<String>,
    /// Opaque continuation data; never render this field as user-facing text.
    #[serde(default)]
    pub continuation: BTreeMap<String, Value>,
}
impl Message {
    pub fn text(role: Role, content: impl Into<String>) -> Self {
        Self {
            role,
            content: Some(content.into()),
            tool_calls: vec![],
            tool_call_id: None,
            continuation: BTreeMap::new(),
        }
    }
    pub fn tool(id: &str, result: &Value) -> Self {
        let mut message = Self::text(Role::Tool, result.to_string());
        message.tool_call_id = Some(id.into());
        message
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    pub input_schema: Value,
}

#[derive(Debug, Clone, Default)]
pub struct Request {
    pub messages: Vec<Message>,
    pub tools: Vec<ToolDefinition>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Usage {
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
    pub cost: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Response {
    pub message: Message,
    pub finish_reason: String,
    pub usage: Usage,
    pub provider_request_id: Option<String>,
    pub model: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Event {
    pub context: CallContext,
    #[serde(flatten)]
    pub kind: EventKind,
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum EventKind {
    Started,
    TextDelta { text: String },
    ToolCallReady { call: ToolCall },
    Usage { usage: Usage },
    Finished { response: Response },
    Failed { error: Error },
}
