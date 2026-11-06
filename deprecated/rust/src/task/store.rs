use super::{sqlite::Connection, vectors::sync_sources, *};
use serde_json::{Value, json};
use std::collections::HashSet;

pub struct TaskStore {
    pub(crate) db: Connection,
}
pub struct OrchestratorApi<'a> {
    store: &'a mut TaskStore,
}
pub struct RecordingApi<'a> {
    store: &'a mut TaskStore,
}

struct Transaction<'a> {
    db: &'a Connection,
    committed: bool,
}
impl Drop for Transaction<'_> {
    fn drop(&mut self) {
        if !self.committed {
            let _ = self.db.exec("ROLLBACK");
        }
    }
}

impl TaskStore {
    pub fn open(path: impl AsRef<std::path::Path>) -> Result<Self> {
        let path = path
            .as_ref()
            .to_str()
            .ok_or_else(|| Error::invalid("Database path must be UTF-8"))?;
        let db = Connection::open(path)?;
        db.exec("BEGIN IMMEDIATE")?;
        let mut migration = Transaction {
            db: &db,
            committed: false,
        };
        // Read after acquiring the lock so concurrent first opens cannot both migrate.
        let version = db.scalar("PRAGMA user_version", &[])?;
        match version.as_str() {
            "0" => db.exec(include_str!("schema.sql"))?,
            "1" => {}
            _ => {
                return Err(Error::new(
                    "SCHEMA_VERSION",
                    format!("Unsupported database schema {version}"),
                ));
            }
        }
        db.exec("COMMIT")?;
        migration.committed = true;
        drop(migration);
        Ok(Self { db })
    }

    pub fn orchestrator(&mut self) -> OrchestratorApi<'_> {
        OrchestratorApi { store: self }
    }
    pub fn recorder(&mut self) -> RecordingApi<'_> {
        RecordingApi { store: self }
    }

    pub(crate) fn transaction<T>(
        &mut self,
        operation: impl FnOnce(&Connection) -> Result<T>,
    ) -> Result<T> {
        self.db.exec("BEGIN IMMEDIATE")?;
        let mut transaction = Transaction {
            db: &self.db,
            committed: false,
        };
        let result = operation(&self.db)?;
        self.db.exec("COMMIT")?;
        transaction.committed = true;
        Ok(result)
    }
}

pub(crate) fn nonempty(name: &str, value: &str) -> Result<()> {
    if value.trim().is_empty() {
        Err(Error::invalid(format!("{name} must not be empty")))
    } else {
        Ok(())
    }
}
pub(crate) fn identifier(db: &Connection) -> Result<String> {
    db.scalar("SELECT lower(hex(randomblob(16)))", &[])
}
fn now(db: &Connection) -> Result<String> {
    db.scalar("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')", &[])
}
pub(crate) fn load_task(db: &Connection, id: &str) -> Result<Task> {
    let rows = db.query("SELECT data FROM tasks WHERE id=?1", &[id])?;
    let row = rows
        .first()
        .ok_or_else(|| Error::new("NOT_FOUND", format!("Task {id} does not exist")))?;
    Ok(serde_json::from_str(&row[0])?)
}

fn save_task(db: &Connection, task: &mut Task) -> Result<()> {
    task.version = task
        .version
        .checked_add(1)
        .filter(|v| *v <= i64::MAX as u64)
        .ok_or_else(|| Error::invalid("Task version overflow"))?;
    task.updated_at = now(db)?;
    db.run(
        "UPDATE tasks SET data=?1,version=?2 WHERE id=?3",
        &[
            &serde_json::to_string(task)?,
            &task.version.to_string(),
            &task.id,
        ],
    )?;
    sync_sources(db, task)
}

fn history(
    db: &Connection,
    task: &Task,
    source: &str,
    run_id: Option<&str>,
    id: Option<&str>,
    data: Value,
) -> Result<()> {
    let generated = identifier(db)?;
    db.run(
        "INSERT INTO history(id,task_id,timestamp,source,run_id,data) VALUES(?1,?2,?3,?4,?5,?6)",
        &[
            id.unwrap_or(&generated),
            &task.id,
            &now(db)?,
            source,
            run_id.unwrap_or(""),
            &serde_json::to_string(&data)?,
        ],
    )
}

pub(crate) fn limit(value: usize) -> usize {
    value.clamp(1, 200)
}

impl OrchestratorApi<'_> {
    pub fn create_task(
        &mut self,
        project_id: &str,
        description: &str,
        tags: Vec<String>,
    ) -> Result<Task> {
        nonempty("project_id", project_id)?;
        nonempty("description", description)?;
        validate_tags(&tags)?;
        self.store.transaction(|db| {
            let timestamp = now(db)?;
            let task = Task {
                id: identifier(db)?,
                project_id: project_id.into(),
                created_at: timestamp.clone(),
                updated_at: timestamp,
                version: 1,
                description: description.into(),
                acceptance_criteria: vec![],
                tags,
                relations: vec![],
                status: TaskStatus::Draft,
                current_step: None,
                state_reason: None,
                result_summary: None,
                links: vec![],
                files: vec![],
                git_refs: vec![],
                input_tokens: None,
                output_tokens: None,
                elapsed_time_ms: None,
            };
            db.run(
                "INSERT INTO tasks(id,project_id,version,data) VALUES(?1,?2,1,?3)",
                &[&task.id, &task.project_id, &serde_json::to_string(&task)?],
            )?;
            sync_sources(db, &task)?;
            history(
                db,
                &task,
                "orchestrator",
                None,
                None,
                json!({"type":"task_created","task":task}),
            )?;
            Ok(task)
        })
    }

    pub fn get_task(&self, id: &str) -> Result<Task> {
        load_task(&self.store.db, id)
    }

    pub fn update_task(&mut self, id: &str, changes: TaskUpdate) -> Result<Task> {
        let recorded_changes = serde_json::to_value(&changes)?;
        self.store.transaction(|db| {
            let mut task = load_task(db, id)?;
            if changes
                .expected_version
                .is_some_and(|version| version != task.version)
            {
                return Err(Error::conflict(format!(
                    "Reload task {id}; its current version is {}",
                    task.version
                )));
            }
            if changes.description.is_some() || changes.acceptance_criteria.is_some() {
                if matches!(
                    task.status,
                    TaskStatus::InProgress | TaskStatus::Completed | TaskStatus::Cancelled
                ) {
                    return Err(Error::new(
                        "TASK_BUSY",
                        "Move the task to draft, ready, or blocked before editing its goal",
                    ));
                }
                // A result for the old goal must not be indexed as the new goal's result.
                task.result_summary = None;
            }
            if let Some(description) = changes.description {
                nonempty("description", &description)?;
                task.description = description;
            }
            if let Some(criteria) = changes.acceptance_criteria {
                for criterion in &criteria {
                    nonempty("acceptance criterion", criterion)?;
                }
                task.acceptance_criteria = criteria;
            }
            if let Some(tags) = changes.tags {
                validate_tags(&tags)?;
                task.tags = tags;
            }
            if let Some(relations) = changes.relations {
                validate_relations(db, &task, &relations)?;
                task.relations = relations;
            }
            if let Some(links) = changes.links {
                let mut replacements = Vec::new();
                let mut urls = HashSet::new();
                for link in links {
                    nonempty("link URL", &link.url)?;
                    if !urls.insert(link.url.clone()) {
                        return Err(Error::invalid("Duplicate link URL"));
                    }
                    let id = task
                        .links
                        .iter()
                        .find(|old| old.link.url == link.url)
                        .map(|old| old.id.clone())
                        .unwrap_or(identifier(db)?);
                    replacements.push(LinkReference { id, link });
                }
                task.links = replacements;
            }
            if let Some(files) = changes.files {
                let mut replacements: Vec<_> = task
                    .files
                    .iter()
                    .filter(|old| old.relation != FileRelation::Linked)
                    .cloned()
                    .collect();
                for file in files {
                    validate_file(&file)?;
                    if replacements.iter().any(|old| {
                        old.relation == FileRelation::Linked && same_file(&old.file, &file)
                    }) {
                        return Err(Error::invalid("Duplicate explicit file reference"));
                    }
                    let id = task
                        .files
                        .iter()
                        .find(|old| {
                            old.relation == FileRelation::Linked && same_file(&old.file, &file)
                        })
                        .map(|old| old.id.clone())
                        .unwrap_or(identifier(db)?);
                    replacements.push(FileReference {
                        id,
                        relation: FileRelation::Linked,
                        file,
                    });
                }
                task.files = replacements;
            }
            save_task(db, &mut task)?;
            history(
                db,
                &task,
                "orchestrator",
                None,
                None,
                json!({"type":"task_updated","version":task.version,"changes":recorded_changes}),
            )?;
            Ok(task)
        })
    }

    pub fn annotate_reference(
        &mut self,
        task_id: &str,
        reference_id: &str,
        comment: &str,
    ) -> Result<Task> {
        self.store.transaction(|db| {
            let mut task = load_task(db, task_id)?;
            if let Some(reference) = task.links.iter_mut().find(|r| r.id == reference_id) {
                reference.link.comment = Some(comment.into());
            } else if let Some(reference) = task.files.iter_mut().find(|r| r.id == reference_id) {
                reference.file.comment = Some(comment.into());
            } else if let Some(reference) = task.git_refs.iter_mut().find(|r| r.id == reference_id)
            {
                reference.comment = Some(comment.into());
            } else {
                return Err(Error::new(
                    "NOT_FOUND",
                    format!("Reference {reference_id} does not belong to task {task_id}"),
                ));
            }
            save_task(db, &mut task)?;
            history(
                db,
                &task,
                "orchestrator",
                None,
                None,
                json!({"type":"reference_annotated","reference_id":reference_id,"comment":comment}),
            )?;
            Ok(task)
        })
    }

    pub fn add_note(&mut self, task_id: &str, text: &str) -> Result<Task> {
        nonempty("note", text)?;
        self.store.transaction(|db| {
            let mut task = load_task(db, task_id)?;
            save_task(db, &mut task)?;
            history(
                db,
                &task,
                "orchestrator",
                None,
                None,
                json!({"type":"note_added","text":text}),
            )?;
            Ok(task)
        })
    }

    pub fn get_history(&self, id: &str, count: usize) -> Result<Vec<HistoryEntry>> {
        load_task(&self.store.db, id)?;
        let rows = self.store.db.query("SELECT sequence,id,timestamp,source,run_id,data FROM history WHERE task_id=?1 ORDER BY sequence DESC LIMIT ?2", &[id, &limit(count).to_string()])?;
        let mut entries = Vec::new();
        for row in rows.into_iter().rev() {
            entries.push(HistoryEntry {
                sequence: row[0]
                    .parse()
                    .map_err(|_| Error::invalid("Invalid stored history sequence"))?,
                id: row[1].clone(),
                task_id: id.into(),
                timestamp: row[2].clone(),
                source: row[3].clone(),
                run_id: (!row[4].is_empty()).then(|| row[4].clone()),
                data: serde_json::from_str(&row[5])?,
            });
        }
        Ok(entries)
    }

    pub fn search_tasks(&self, query: &SearchQuery) -> Result<Vec<TaskSummary>> {
        nonempty("project_id", &query.project_id)?;
        let rows = self.store.db.query("SELECT data FROM tasks WHERE project_id=?1 ORDER BY json_extract(data,'$.updated_at') DESC,id", &[&query.project_id])?;
        let mut hits = Vec::new();
        for row in rows {
            let task: Task = serde_json::from_str(&row[0])?;
            if !matches_filters(&task, query) {
                continue;
            }
            if let Some(text) = &query.text {
                let mut content = vec![task.description.as_str()];
                content.extend(task.acceptance_criteria.iter().map(String::as_str));
                content.extend(task.tags.iter().map(String::as_str));
                content.extend(task.result_summary.as_deref());
                for reference in &task.links {
                    content.push(&reference.link.url);
                    content.extend(reference.link.label.as_deref());
                    content.extend(reference.link.comment.as_deref());
                }
                for reference in &task.files {
                    content.push(&reference.file.path);
                    content.extend(reference.file.symbol.as_deref());
                    content.extend(reference.file.comment.as_deref());
                }
                let searchable = content.join(" ");
                if !searchable.to_lowercase().contains(&text.to_lowercase()) {
                    let note_match = self.store.db.query("SELECT json_extract(data,'$.text') FROM history WHERE task_id=?1 AND json_extract(data,'$.type')='note_added'", &[&task.id])?
                        .iter().any(|entry| entry[0].to_lowercase().contains(&text.to_lowercase()));
                    if !note_match {
                        continue;
                    }
                }
            }
            hits.push(TaskSummary::from(&task));
            if hits.len() == limit(query.limit) {
                break;
            }
        }
        Ok(hits)
    }
}

pub(crate) fn matches_filters(task: &Task, query: &SearchQuery) -> bool {
    task.project_id == query.project_id
        && query.status.is_none_or(|status| task.status == status)
        && query.tag.as_ref().is_none_or(|tag| task.tags.contains(tag))
}

fn validate_tags(tags: &[String]) -> Result<()> {
    let mut unique = HashSet::new();
    for tag in tags {
        nonempty("tag", tag)?;
        if !unique.insert(tag) {
            return Err(Error::invalid("Duplicate tag"));
        }
    }
    Ok(())
}

fn validate_relations(db: &Connection, task: &Task, relations: &[TaskRelation]) -> Result<()> {
    for relation in relations {
        if relation.task_id == task.id {
            return Err(Error::invalid("Task cannot reference itself"));
        }
        let target = load_task(db, &relation.task_id)?;
        if target.project_id != task.project_id {
            return Err(Error::invalid(
                "Related tasks must belong to the same project",
            ));
        }
        if relation.kind == RelationKind::BlockedBy {
            let mut stack = vec![target.id];
            let mut visited = HashSet::new();
            while let Some(id) = stack.pop() {
                if id == task.id {
                    return Err(Error::invalid(
                        "blocked_by relationships must not form a cycle",
                    ));
                }
                if visited.insert(id.clone()) {
                    stack.extend(
                        load_task(db, &id)?
                            .relations
                            .into_iter()
                            .filter(|r| r.kind == RelationKind::BlockedBy)
                            .map(|r| r.task_id),
                    );
                }
            }
        }
    }
    Ok(())
}

fn same_file(a: &FileInput, b: &FileInput) -> bool {
    a.repository_id == b.repository_id
        && a.path == b.path
        && a.commit_hash == b.commit_hash
        && a.symbol == b.symbol
        && a.start_line == b.start_line
        && a.end_line == b.end_line
}

fn validate_file(file: &FileInput) -> Result<()> {
    nonempty("repository_id", &file.repository_id)?;
    nonempty("path", &file.path)?;
    if file.path.starts_with(['/', '\\']) || file.path.split(['/', '\\']).any(|part| part == "..") {
        return Err(Error::invalid(
            "File paths must be repository-relative without '..' components",
        ));
    }
    match (file.start_line, file.end_line) {
        (None, None) => {}
        (Some(start), Some(end)) if start > 0 && end >= start => {}
        _ => {
            return Err(Error::invalid(
                "Line ranges need both start_line and end_line, with 1 <= start <= end",
            ));
        }
    }
    Ok(())
}

impl RecordingApi<'_> {
    pub fn record_event(&mut self, event: RecordEvent) -> Result<EventReceipt> {
        nonempty("event id", &event.id)?;
        if let Some(run) = &event.run_id {
            nonempty("run_id", run)?;
        }
        self.store.transaction(|db| {
            let mut task = load_task(db, &event.task_id)?;
            let encoded = serde_json::to_string(&event)?;
            let existing =
                db.query("SELECT data FROM recorded_events WHERE id=?1", &[&event.id])?;
            if let Some(row) = existing.first() {
                if row[0] != encoded {
                    return Err(Error::conflict(
                        "Event ID was already used with different content",
                    ));
                }
                return Ok(EventReceipt {
                    id: event.id.clone(),
                    duplicate: true,
                    task_version: task.version,
                });
            }
            match &event.change {
                RecordedChange::WorkflowStatusChanged {
                    sequence,
                    status,
                    current_step,
                    state_reason,
                } => {
                    workflow_sequence(db, &task.id, *sequence)?;
                    transition(task.status, *status)?;
                    if *status == TaskStatus::Completed {
                        return Err(Error::invalid(
                            "Use workflow_finished to record completion and its result",
                        ));
                    }
                    task.status = *status;
                    task.current_step = current_step.clone();
                    task.state_reason = state_reason.clone();
                }
                RecordedChange::WorkflowFinished {
                    sequence,
                    status,
                    result_summary,
                    elapsed_time_ms,
                } => {
                    workflow_sequence(db, &task.id, *sequence)?;
                    if !matches!(
                        status,
                        TaskStatus::Completed | TaskStatus::Blocked | TaskStatus::Cancelled
                    ) {
                        return Err(Error::invalid(
                            "Finished workflow must be completed, blocked, or cancelled",
                        ));
                    }
                    transition(task.status, *status)?;
                    nonempty("result_summary", result_summary)?;
                    let run = event
                        .run_id
                        .as_deref()
                        .ok_or_else(|| Error::invalid("Workflow outcome requires run_id"))?;
                    if *elapsed_time_ms > i64::MAX as u64 {
                        return Err(Error::invalid("Duration is too large"));
                    }
                    if !db
                        .query(
                            "SELECT 1 FROM workflow_outcomes WHERE task_id=?1 AND run_id=?2",
                            &[&task.id, run],
                        )?
                        .is_empty()
                    {
                        return Err(Error::conflict(
                            "This workflow run already has a recorded outcome",
                        ));
                    }
                    db.run(
                        "INSERT INTO workflow_outcomes(task_id,run_id,elapsed_ms) VALUES(?1,?2,?3)",
                        &[&task.id, run, &elapsed_time_ms.to_string()],
                    )?;
                    let duration = db.scalar(
                        "SELECT sum(elapsed_ms) FROM workflow_outcomes WHERE task_id=?1",
                        &[&task.id],
                    )?;
                    task.elapsed_time_ms = Some(
                        duration
                            .parse()
                            .map_err(|_| Error::invalid("Duration total overflow"))?,
                    );
                    task.status = *status;
                    task.current_step = None;
                    task.state_reason =
                        (*status != TaskStatus::Completed).then(|| result_summary.clone());
                    task.result_summary = Some(result_summary.clone());
                }
                RecordedChange::FilesObserved { files } => {
                    for observed in files {
                        validate_file(&observed.file)?;
                        if observed.relation == FileRelation::Linked {
                            return Err(Error::invalid(
                                "Runtime observations must be consulted or modified",
                            ));
                        }
                        if !task.files.iter().any(|old| {
                            old.relation == observed.relation
                                && same_file(&old.file, &observed.file)
                        }) {
                            task.files.push(FileReference {
                                id: identifier(db)?,
                                relation: observed.relation,
                                file: observed.file.clone(),
                            });
                        }
                    }
                }
                RecordedChange::GitRecorded { reference } => {
                    nonempty("repository_id", &reference.repository_id)?;
                    nonempty("commit_hash", &reference.commit_hash)?;
                    if reference.kind == GitKind::Checkpoint
                        && reference
                            .development_head
                            .as_ref()
                            .is_none_or(|head| head.trim().is_empty())
                    {
                        return Err(Error::invalid("Checkpoint requires development_head"));
                    }
                    if !task
                        .git_refs
                        .iter()
                        .any(|old| old.reference == *reference && old.run_id == event.run_id)
                    {
                        task.git_refs.push(GitReference {
                            id: identifier(db)?,
                            reference: reference.clone(),
                            run_id: event.run_id.clone(),
                            comment: None,
                        });
                    }
                }
                RecordedChange::UsageRecorded {
                    model_call_id,
                    input_tokens,
                    output_tokens,
                } => {
                    nonempty("model_call_id", model_call_id)?;
                    let counts = serde_json::to_string(&(input_tokens, output_tokens))?;
                    let existing = db.query(
                        "SELECT data FROM usage_calls WHERE task_id=?1 AND call_id=?2",
                        &[&task.id, model_call_id],
                    )?;
                    if let Some(row) = existing.first() {
                        if row[0] != counts {
                            return Err(Error::conflict(
                                "Model-call ID reused with different usage",
                            ));
                        }
                    } else {
                        db.run(
                            "INSERT INTO usage_calls(task_id,call_id,data) VALUES(?1,?2,?3)",
                            &[&task.id, model_call_id, &counts],
                        )?;
                    }
                    let mut input = Some(0_u64);
                    let mut output = Some(0_u64);
                    for row in
                        db.query("SELECT data FROM usage_calls WHERE task_id=?1", &[&task.id])?
                    {
                        let (i, o): (Option<u64>, Option<u64>) = serde_json::from_str(&row[0])?;
                        input = add_measurement(input, i)?;
                        output = add_measurement(output, o)?;
                    }
                    task.input_tokens = input;
                    task.output_tokens = output;
                }
                RecordedChange::AgentResultRecorded { summary } => {
                    nonempty("agent result", summary)?;
                }
            }
            save_task(db, &mut task)?;
            history(
                db,
                &task,
                event.change.source(),
                event.run_id.as_deref(),
                Some(&event.id),
                serde_json::to_value(&event.change)?,
            )?;
            db.run(
                "INSERT INTO recorded_events(id,task_id,data) VALUES(?1,?2,?3)",
                &[&event.id, &task.id, &encoded],
            )?;
            Ok(EventReceipt {
                id: event.id,
                duplicate: false,
                task_version: task.version,
            })
        })
    }
}

fn add_measurement(a: Option<u64>, b: Option<u64>) -> Result<Option<u64>> {
    match (a, b) {
        (Some(a), Some(b)) => a
            .checked_add(b)
            .map(Some)
            .ok_or_else(|| Error::invalid("Token total overflow")),
        _ => Ok(None),
    }
}

fn workflow_sequence(db: &Connection, task_id: &str, sequence: u64) -> Result<()> {
    let current: u64 = db
        .scalar(
            "SELECT workflow_sequence FROM tasks WHERE id=?1",
            &[task_id],
        )?
        .parse()
        .map_err(|_| Error::invalid("Invalid workflow sequence"))?;
    if sequence != current + 1 || sequence > i64::MAX as u64 {
        return Err(Error::conflict(format!(
            "Expected workflow sequence {}; retry missing events in order",
            current + 1
        )));
    }
    db.run(
        "UPDATE tasks SET workflow_sequence=?1 WHERE id=?2",
        &[&sequence.to_string(), task_id],
    )
}

fn transition(from: TaskStatus, to: TaskStatus) -> Result<()> {
    use TaskStatus::*;
    let valid = matches!(
        (from, to),
        (Draft, Ready | Cancelled)
            | (Ready, InProgress | Cancelled)
            | (InProgress, InProgress | Blocked | Completed | Cancelled)
            | (Blocked, Ready | InProgress | Cancelled)
            | (Completed | Cancelled, Ready)
    );
    if valid {
        Ok(())
    } else {
        Err(Error::new(
            "INVALID_TRANSITION",
            format!("Cannot move task from {from:?} to {to:?}"),
        ))
    }
}
