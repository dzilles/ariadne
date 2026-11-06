use ariadne_tasks::task::*;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Plan {
    pub project_id: String,
    pub repository_id: String,
    pub tasks: Vec<PlannedTask>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlannedTask {
    pub key: String,
    pub title: String,
    pub description: String,
    pub acceptance_criteria: Vec<String>,
    pub tags: Vec<String>,
    pub blocked_by: Vec<String>,
    #[serde(default)]
    pub related_to: Vec<String>,
    pub state: TaskStatus,
    #[serde(default)]
    pub state_reason: Option<String>,
    pub files: Vec<PlannedFile>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlannedFile {
    pub path: String,
    pub comment: String,
}

#[derive(Serialize)]
pub struct SeedSummary {
    pub project_id: String,
    pub tasks: usize,
    pub dependency_edges: usize,
    pub indexed_sources: usize,
}

fn invalid(message: impl Into<String>) -> Error {
    Error {
        code: "INVALID_FIXTURE",
        message: message.into(),
    }
}

pub fn read_plan() -> Result<Plan> {
    let plan: Plan = serde_json::from_str(include_str!("fixtures/android-chat-tasks.json"))?;
    if plan.tasks.len() < 20 {
        return Err(invalid("The example must contain at least 20 tasks"));
    }
    let keys: HashMap<_, _> = plan
        .tasks
        .iter()
        .enumerate()
        .map(|(i, task)| (task.key.as_str(), i))
        .collect();
    if keys.len() != plan.tasks.len() {
        return Err(invalid("Task keys must be unique"));
    }
    for (position, task) in plan.tasks.iter().enumerate() {
        if position > 0 && task.blocked_by.is_empty() {
            return Err(invalid(format!(
                "{} must depend on an earlier task",
                task.key
            )));
        }
        let mut unique = HashSet::new();
        for dependency in &task.blocked_by {
            let index = keys
                .get(dependency.as_str())
                .ok_or_else(|| invalid(format!("Unknown dependency {dependency}")))?;
            if *index >= position || !unique.insert(dependency) {
                return Err(invalid(
                    "Dependencies must be unique and appear earlier in the plan; cycles are not allowed",
                ));
            }
            if task.state != TaskStatus::Draft && plan.tasks[*index].state != TaskStatus::Completed
            {
                return Err(invalid(format!(
                    "{} is not a draft, but prerequisite {dependency} is unfinished",
                    task.key
                )));
            }
        }
        for related in &task.related_to {
            if !keys.contains_key(related.as_str()) || related == &task.key {
                return Err(invalid("Invalid related_to reference"));
            }
        }
        if task.state == TaskStatus::Blocked
            && task
                .state_reason
                .as_ref()
                .is_none_or(|s| s.trim().is_empty())
        {
            return Err(invalid("Blocked examples require a reason"));
        }
    }
    Ok(plan)
}

pub fn populate(store: &mut TaskStore, plan: &Plan) -> Result<SeedSummary> {
    if !store
        .orchestrator()
        .search_tasks(&SearchQuery {
            project_id: plan.project_id.clone(),
            text: None,
            status: None,
            tag: None,
            limit: 1,
        })?
        .is_empty()
    {
        return Err(invalid(
            "Seed project already exists; start with an empty database",
        ));
    }

    store.register_embedding_model(&DemoEmbedder.model())?;
    let mut ids = HashMap::new();
    for spec in &plan.tasks {
        let tags = [
            vec![spec.key.clone(), "system-fixture".into()],
            spec.tags.clone(),
        ]
        .concat();
        let task = store.orchestrator().create_task(
            &plan.project_id,
            &format!("{}: {}\n\n{}", spec.key, spec.title, spec.description),
            tags,
        )?;
        ids.insert(spec.key.clone(), task.id);
    }

    for (position, spec) in plan.tasks.iter().enumerate() {
        let id = &ids[&spec.key];
        let files: Vec<_> = spec
            .files
            .iter()
            .map(|file| FileInput {
                repository_id: plan.repository_id.clone(),
                path: file.path.clone(),
                commit_hash: None,
                symbol: None,
                start_line: None,
                end_line: None,
                comment: Some(file.comment.clone()),
            })
            .collect();
        let mut relations: Vec<_> = spec
            .blocked_by
            .iter()
            .map(|key| TaskRelation {
                task_id: ids[key].clone(),
                kind: RelationKind::BlockedBy,
            })
            .collect();
        relations.extend(spec.related_to.iter().map(|key| TaskRelation {
            task_id: ids[key].clone(),
            kind: RelationKind::RelatedTo,
        }));
        store.orchestrator().update_task(id, TaskUpdate {
            acceptance_criteria: Some(spec.acceptance_criteria.clone()), relations: Some(relations), files: Some(files.clone()),
            links: Some(vec![LinkInput {
                url: format!("https://example.com/android-ai-chat/tasks/{}", spec.key),
                label: Some(format!("{} planning reference", spec.key)),
                comment: Some("Fictional URL used to exercise reference storage; no network access is required.".into()),
            }]), ..Default::default()
        })?;
        store.orchestrator().add_note(id, &format!(
            "Synthetic system-test task; no Android application has actually been built. Planned prerequisites: {}.",
            if spec.blocked_by.is_empty() { "none".into() } else { spec.blocked_by.join(", ") },
        ))?;

        let run_id = format!("fixture-run-{}", spec.key);
        let mut emit = |suffix: &str, change| {
            store
                .recorder()
                .record_event(RecordEvent {
                    id: format!("fixture-{}-{suffix}", spec.key),
                    task_id: id.clone(),
                    run_id: Some(run_id.clone()),
                    change,
                })
                .map(|_| ())
        };
        let state_event =
            |sequence, status, current_step, state_reason| RecordedChange::WorkflowStatusChanged {
                sequence,
                status,
                current_step,
                state_reason,
            };
        if spec.state == TaskStatus::Draft {
            continue;
        }
        emit("ready", state_event(1, TaskStatus::Ready, None, None))?;
        if spec.state == TaskStatus::Ready {
            continue;
        }
        emit(
            "started",
            state_event(2, TaskStatus::InProgress, Some("code".into()), None),
        )?;
        emit(
            "usage",
            RecordedChange::UsageRecorded {
                model_call_id: format!("fixture-call-{}", spec.key),
                input_tokens: Some(700 + position as u64 * 13),
                output_tokens: Some(200 + position as u64 * 5),
            },
        )?;
        emit(
            "files",
            RecordedChange::FilesObserved {
                files: files
                    .iter()
                    .map(|file| {
                        let mut file = file.clone();
                        file.comment = None;
                        ObservedFile {
                            relation: if spec.state == TaskStatus::Completed {
                                FileRelation::Modified
                            } else {
                                FileRelation::Consulted
                            },
                            file,
                        }
                    })
                    .collect(),
            },
        )?;
        if spec.state == TaskStatus::Completed {
            emit(
                "git",
                RecordedChange::GitRecorded {
                    reference: GitInput {
                        repository_id: plan.repository_id.clone(),
                        commit_hash: format!("{:040x}", position + 1),
                        kind: GitKind::Development,
                        development_head: None,
                    },
                },
            )?;
            emit(
                "agent-result",
                RecordedChange::AgentResultRecorded {
                    summary: format!(
                        "Synthetic fixture result: {} passed its mock acceptance checks.",
                        spec.title
                    ),
                },
            )?;
            emit(
                "finished",
                RecordedChange::WorkflowFinished {
                    sequence: 3,
                    status: TaskStatus::Completed,
                    result_summary: format!(
                        "Synthetic completion: {}. Mock acceptance checks passed; no real implementation is included.",
                        spec.title
                    ),
                    elapsed_time_ms: 4000 + position as u64 * 1500,
                },
            )?;
        } else if spec.state == TaskStatus::Blocked {
            emit(
                "blocked",
                state_event(
                    3,
                    TaskStatus::Blocked,
                    Some("code".into()),
                    spec.state_reason.clone(),
                ),
            )?;
        } else if spec.state == TaskStatus::InProgress {
            emit(
                "checkpoint",
                RecordedChange::GitRecorded {
                    reference: GitInput {
                        repository_id: plan.repository_id.clone(),
                        commit_hash: format!("{:040x}", 1000 + position),
                        kind: GitKind::Checkpoint,
                        development_head: Some(format!("{:040x}", 6)),
                    },
                },
            )?;
        } else {
            return Err(invalid("Unsupported seed state"));
        }
    }

    while !store
        .index_status(&plan.project_id, &DemoEmbedder.model().id)?
        .complete
    {
        let progress = store.index_pending(&DemoEmbedder, 200)?;
        if progress.applied == 0 {
            return Err(invalid("The seed index could not make progress"));
        }
    }
    Ok(SeedSummary {
        project_id: plan.project_id.clone(),
        tasks: plan.tasks.len(),
        dependency_edges: plan.tasks.iter().map(|task| task.blocked_by.len()).sum(),
        indexed_sources: store
            .index_status(&plan.project_id, &DemoEmbedder.model().id)?
            .ready,
    })
}
