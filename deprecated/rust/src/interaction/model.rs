use crate::Error;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Command {
    pub command_id: String,
    pub session_id: String,
    pub payload: CommandKind,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum CommandKind {
    SendMessage { text: String },
    CancelRun { run_id: String },
    RespondToInput { request_id: String, answer: Value },
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Source {
    pub component: String,
    pub instance_id: String,
}
impl Source {
    pub fn new(component: &str, instance: &str) -> Self {
        Self {
            component: component.into(),
            instance_id: instance.into(),
        }
    }
}
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct EventContext {
    pub command_id: Option<String>,
    pub run_id: Option<String>,
    pub task_id: Option<String>,
    pub call_id: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    pub event_id: String,
    pub session_id: String,
    pub sequence: u64,
    pub source: Source,
    pub context: EventContext,
    pub payload: EventKind,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum EventKind {
    MessageStarted {
        message_id: String,
    },
    MessageDelta {
        message_id: String,
        text: String,
    },
    MessageFinished {
        message_id: String,
        text: String,
    },
    ActivityUpdated {
        label: String,
        state: String,
    },
    InputRequested {
        request_id: String,
        prompt: String,
        answer_type: String,
    },
    InputResolved {
        request_id: String,
    },
    RunFinished {
        outcome: String,
    },
    Error {
        error: Error,
    },
}
