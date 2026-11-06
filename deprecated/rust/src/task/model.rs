use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Draft,
    Ready,
    InProgress,
    Blocked,
    Completed,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RelationKind {
    BlockedBy,
    RelatedTo,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskRelation {
    pub task_id: String,
    pub kind: RelationKind,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LinkInput {
    pub url: String,
    #[serde(default)]
    pub label: Option<String>,
    #[serde(default)]
    pub comment: Option<String>,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LinkReference {
    pub id: String,
    #[serde(flatten)]
    pub link: LinkInput,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FileRelation {
    Linked,
    Consulted,
    Modified,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileInput {
    pub repository_id: String,
    pub path: String,
    #[serde(default)]
    pub commit_hash: Option<String>,
    #[serde(default)]
    pub symbol: Option<String>,
    #[serde(default)]
    pub start_line: Option<u32>,
    #[serde(default)]
    pub end_line: Option<u32>,
    #[serde(default)]
    pub comment: Option<String>,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FileReference {
    pub id: String,
    pub relation: FileRelation,
    #[serde(flatten)]
    pub file: FileInput,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GitKind {
    Development,
    Checkpoint,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GitInput {
    pub repository_id: String,
    pub commit_hash: String,
    pub kind: GitKind,
    #[serde(default)]
    pub development_head: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GitReference {
    pub id: String,
    pub run_id: Option<String>,
    pub comment: Option<String>,
    #[serde(flatten)]
    pub reference: GitInput,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Task {
    pub id: String,
    pub project_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub version: u64,
    pub description: String,
    pub acceptance_criteria: Vec<String>,
    pub tags: Vec<String>,
    pub relations: Vec<TaskRelation>,
    pub status: TaskStatus,
    pub current_step: Option<String>,
    pub state_reason: Option<String>,
    pub result_summary: Option<String>,
    pub links: Vec<LinkReference>,
    pub files: Vec<FileReference>,
    pub git_refs: Vec<GitReference>,
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
    pub elapsed_time_ms: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskSummary {
    pub id: String,
    pub project_id: String,
    pub description: String,
    pub status: TaskStatus,
    pub tags: Vec<String>,
    pub updated_at: String,
}
impl From<&Task> for TaskSummary {
    fn from(task: &Task) -> Self {
        Self {
            id: task.id.clone(),
            project_id: task.project_id.clone(),
            description: task.description.clone(),
            status: task.status,
            tags: task.tags.clone(),
            updated_at: task.updated_at.clone(),
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskUpdate {
    pub expected_version: Option<u64>,
    pub description: Option<String>,
    pub acceptance_criteria: Option<Vec<String>>,
    pub tags: Option<Vec<String>>,
    pub relations: Option<Vec<TaskRelation>>,
    pub links: Option<Vec<LinkInput>>,
    pub files: Option<Vec<FileInput>>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchQuery {
    pub project_id: String,
    #[serde(default)]
    pub text: Option<String>,
    #[serde(default)]
    pub status: Option<TaskStatus>,
    #[serde(default)]
    pub tag: Option<String>,
    #[serde(default = "default_limit")]
    pub limit: usize,
}
pub fn default_limit() -> usize {
    20
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    pub sequence: u64,
    pub id: String,
    pub task_id: String,
    pub timestamp: String,
    pub source: String,
    pub run_id: Option<String>,
    pub data: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecordEvent {
    pub id: String,
    pub task_id: String,
    #[serde(default)]
    pub run_id: Option<String>,
    pub change: RecordedChange,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum RecordedChange {
    WorkflowStatusChanged {
        sequence: u64,
        status: TaskStatus,
        #[serde(default)]
        current_step: Option<String>,
        #[serde(default)]
        state_reason: Option<String>,
    },
    WorkflowFinished {
        sequence: u64,
        status: TaskStatus,
        result_summary: String,
        elapsed_time_ms: u64,
    },
    FilesObserved {
        files: Vec<ObservedFile>,
    },
    AgentResultRecorded {
        summary: String,
    },
    GitRecorded {
        reference: GitInput,
    },
    UsageRecorded {
        model_call_id: String,
        input_tokens: Option<u64>,
        output_tokens: Option<u64>,
    },
}
impl RecordedChange {
    pub(crate) fn source(&self) -> &'static str {
        match self {
            Self::WorkflowStatusChanged { .. } | Self::WorkflowFinished { .. } => "workflow_engine",
            Self::GitRecorded { .. } => "git_tracker",
            _ => "runtime",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ObservedFile {
    pub relation: FileRelation,
    #[serde(flatten)]
    pub file: FileInput,
}

#[derive(Debug, Clone, Serialize)]
pub struct EventReceipt {
    pub id: String,
    pub duplicate: bool,
    pub task_version: u64,
}
