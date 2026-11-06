use super::*;
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Role {
    Orchestrator,
    Recorder,
    Indexer,
}

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Request {
    CreateTask {
        project_id: String,
        description: String,
        #[serde(default)]
        tags: Vec<String>,
    },
    UpdateTask {
        id: String,
        expected_version: Option<u64>,
        description: Option<String>,
        acceptance_criteria: Option<Vec<String>>,
        tags: Option<Vec<String>>,
        relations: Option<Vec<TaskRelation>>,
        links: Option<Vec<LinkInput>>,
        files: Option<Vec<FileInput>>,
    },
    GetTask {
        id: String,
    },
    AnnotateReference {
        task_id: String,
        reference_id: String,
        comment: String,
    },
    AddNote {
        task_id: String,
        text: String,
    },
    SearchTasks {
        project_id: String,
        text: Option<String>,
        status: Option<TaskStatus>,
        tag: Option<String>,
        #[serde(default = "default_limit")]
        limit: usize,
        #[serde(default)]
        mode: SearchMode,
    },
    GetHistory {
        id: String,
        #[serde(default = "default_limit")]
        limit: usize,
    },
    RecordEvent {
        event: RecordEvent,
    },
    IndexPending {
        #[serde(default = "default_limit")]
        limit: usize,
    },
    IndexStatus {
        project_id: String,
    },
    RebuildIndex,
}

#[derive(Default, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum SearchMode {
    #[default]
    Keyword,
    Semantic,
}

pub(super) fn execute(store: &mut TaskStore, role: Role, request: Request) -> Result<Value> {
    let required = match &request {
        Request::RecordEvent { .. } => Role::Recorder,
        Request::IndexPending { .. } | Request::IndexStatus { .. } | Request::RebuildIndex => {
            Role::Indexer
        }
        _ => Role::Orchestrator,
    };
    if role != required {
        return Err(Error {
            code: "FORBIDDEN",
            message: "This operation is not available to the selected API role".into(),
        });
    }
    let value = match request {
        Request::CreateTask {
            project_id,
            description,
            tags,
        } => serde_json::to_value(store.orchestrator().create_task(
            &project_id,
            &description,
            tags,
        )?)?,
        Request::UpdateTask {
            id,
            expected_version,
            description,
            acceptance_criteria,
            tags,
            relations,
            links,
            files,
        } => {
            let update = TaskUpdate {
                expected_version,
                description,
                acceptance_criteria,
                tags,
                relations,
                links,
                files,
            };
            serde_json::to_value(store.orchestrator().update_task(&id, update)?)?
        }
        Request::GetTask { id } => serde_json::to_value(store.orchestrator().get_task(&id)?)?,
        Request::AnnotateReference {
            task_id,
            reference_id,
            comment,
        } => serde_json::to_value(store.orchestrator().annotate_reference(
            &task_id,
            &reference_id,
            &comment,
        )?)?,
        Request::AddNote { task_id, text } => {
            serde_json::to_value(store.orchestrator().add_note(&task_id, &text)?)?
        }
        Request::SearchTasks {
            project_id,
            text,
            status,
            tag,
            limit,
            mode,
        } => {
            let query = SearchQuery {
                project_id,
                text,
                status,
                tag,
                limit,
            };
            match mode {
                SearchMode::Keyword => {
                    serde_json::to_value(store.orchestrator().search_tasks(&query)?)?
                }
                SearchMode::Semantic => {
                    serde_json::to_value(store.semantic_search(&query, &DemoEmbedder)?)?
                }
            }
        }
        Request::GetHistory { id, limit } => {
            serde_json::to_value(store.orchestrator().get_history(&id, limit)?)?
        }
        Request::RecordEvent { event } => {
            serde_json::to_value(store.recorder().record_event(event)?)?
        }
        Request::IndexPending { limit } => {
            serde_json::to_value(store.index_pending(&DemoEmbedder, limit)?)?
        }
        Request::IndexStatus { project_id } => {
            serde_json::to_value(store.index_status(&project_id, &DemoEmbedder.model().id)?)?
        }
        Request::RebuildIndex => {
            store.rebuild_embeddings(&DemoEmbedder.model().id)?;
            json!({"queued":true})
        }
    };
    Ok(value)
}

fn invalid(message: &str) -> Error {
    Error {
        code: "VALIDATION_ERROR",
        message: message.into(),
    }
}

pub fn tool_definitions() -> Vec<Value> {
    let text = || json!({"type":"string"});
    let strings = || json!({"type":"array","items":{"type":"string"}});
    let optional_text = || json!({"type":["string","null"]});
    let file = json!({"type":"object","additionalProperties":false,"required":["repository_id","path"],"properties":{
        "repository_id":text(),"path":text(),"commit_hash":optional_text(),"symbol":optional_text(),
        "start_line":{"type":["integer","null"],"minimum":1},"end_line":{"type":["integer","null"],"minimum":1},"comment":optional_text()
    }});
    let link = json!({"type":"object","additionalProperties":false,"required":["url"],"properties":{
        "url":text(),"label":optional_text(),"comment":optional_text()
    }});
    let relation = json!({"type":"object","additionalProperties":false,"required":["task_id","kind"],"properties":{
        "task_id":text(),"kind":{"type":"string","enum":["blocked_by","related_to"]}
    }});
    let tool = |name: &str, description: &str, properties: Value, required: Vec<&str>| {
        json!({
            "name":name,"description":description,
            "input_schema":{"type":"object","additionalProperties":false,"properties":properties,"required":required}
        })
    };
    vec![
        tool(
            "create_task",
            "Create a draft task in a project. Returns the task and generated ID.",
            json!({"project_id":text(),"description":text(),"tags":strings()}),
            vec!["project_id", "description"],
        ),
        tool(
            "update_task",
            "Edit the task definition. Omitted fields are unchanged. Lists replace explicit entries; observations survive. Goal changes require draft, ready, or blocked state.",
            json!({
                "id":text(),"expected_version":{"type":"integer","minimum":1},"description":text(),"acceptance_criteria":strings(),"tags":strings(),
                "relations":{"type":"array","items":relation},"links":{"type":"array","items":link},"files":{"type":"array","items":file}
            }),
            vec!["id"],
        ),
        tool(
            "get_task",
            "Read the current task, stable reference IDs, usage, and record version. History is fetched separately.",
            json!({"id":text()}),
            vec!["id"],
        ),
        tool(
            "annotate_reference",
            "Set a reference comment explaining its relevance; observed file and Git facts are preserved.",
            json!({"task_id":text(),"reference_id":text(),"comment":text()}),
            vec!["task_id", "reference_id", "comment"],
        ),
        tool(
            "add_note",
            "Append a user clarification, decision, or finding to task history.",
            json!({"task_id":text(),"text":text()}),
            vec!["task_id", "text"],
        ),
        tool(
            "search_tasks",
            "Search within one project. Keyword mode is immediate; semantic mode uses the current vector index and reports index completeness. This prototype CLI uses token-hash demo vectors.",
            json!({
                "project_id":text(),"text":text(),"status":{"type":"string","enum":["draft","ready","in_progress","blocked","completed","cancelled"]},"tag":text(),
                "limit":{"type":"integer","minimum":1,"maximum":200,"default":20},"mode":{"type":"string","enum":["keyword","semantic"],"default":"keyword"}
            }),
            vec!["project_id"],
        ),
        tool(
            "get_history",
            "Read the most recent history entries, returned in chronological recording order.",
            json!({"id":text(),"limit":{"type":"integer","minimum":1,"maximum":200,"default":20}}),
            vec!["id"],
        ),
    ]
}

/// Execute only the orchestrator-facing tools; internal recorder/indexer calls are rejected.
pub fn call(store: &mut TaskStore, name: &str, arguments: Value) -> Result<Value> {
    if !tool_definitions().iter().any(|tool| tool["name"] == name) {
        return Err(Error::new("FORBIDDEN", "Unknown or internal task tool"));
    }
    let mut arguments = arguments
        .as_object()
        .cloned()
        .ok_or_else(|| invalid("Tool arguments must be an object"))?;
    if arguments.contains_key("op") {
        return Err(invalid("Tool arguments must not include op"));
    }
    arguments.insert("op".into(), json!(name));
    execute(
        store,
        Role::Orchestrator,
        serde_json::from_value(Value::Object(arguments))?,
    )
}
