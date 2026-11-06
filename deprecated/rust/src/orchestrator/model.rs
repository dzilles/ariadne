use crate::{
    Error,
    llm::{Message, Role, Usage},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    Idle,
    Running,
    Interrupted,
    Failed,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Entry {
    pub id: String,
    pub message: Message,
    pub call_id: Option<String>,
    pub usage: Option<Usage>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Conversation {
    pub id: String,
    pub project_id: String,
    pub profile_id: String,
    pub snapshot_id: String,
    pub model: String,
    pub provider_id: String,
    pub title: String,
    pub version: u64,
    pub updated_at: String,
    pub state: State,
    pub active_run_id: Option<String>,
    pub last_error: Option<Error>,
    pub entries: Vec<Entry>,
}
impl Conversation {
    /// Only display content and orchestrator tool activity; omit prompts and continuation data.
    pub fn view(&self) -> Value {
        json!({"id":self.id,"project_id":self.project_id,"profile_id":self.profile_id,"snapshot_id":self.snapshot_id,"model":self.model,"provider_id":self.provider_id,
            "title":self.title,"updated_at":self.updated_at,"state":self.state,"active_run_id":self.active_run_id,"last_error":self.last_error,
            "messages":self.entries.iter().filter(|entry| entry.message.role != Role::System).map(|entry|json!({
                "id":entry.id,"role":entry.message.role,"content":entry.message.content,
                "tool_calls":entry.message.tool_calls.iter().map(|call|json!({"id":call.id,"name":call.name})).collect::<Vec<_>>()
            })).collect::<Vec<_>>()})
    }
}
