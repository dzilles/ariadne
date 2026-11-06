use super::*;
use crate::{
    Error, Result,
    configuration::{Component, ConfigurationStore},
    interaction::new_id,
    llm::{Binding, Message, Role},
    task::sqlite::Connection,
};
use serde_json::json;
use std::{
    collections::{BTreeMap, HashSet},
    path::Path,
};

pub struct ConversationStore {
    db: Connection,
}
impl ConversationStore {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let db = Connection::open(
            path.as_ref()
                .to_str()
                .ok_or_else(|| Error::invalid("Conversation database path must be UTF-8"))?,
        )?;
        db.exec("CREATE TABLE IF NOT EXISTS orchestrator_conversations (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data))); CREATE INDEX IF NOT EXISTS orchestrator_conversations_project ON orchestrator_conversations(project_id,updated_at);")?;
        Ok(Self { db })
    }
    pub fn create(
        &self,
        config: &ConfigurationStore,
        project_id: &str,
        profile_id: &str,
        project_summary: &str,
    ) -> Result<Conversation> {
        if project_id.trim().is_empty() {
            return Err(Error::invalid("Project ID is required"));
        }
        let snapshot = config.create_snapshot()?;
        let binding = Binding::from_snapshot(&snapshot, profile_id)?;
        let profile = &snapshot.configuration.profiles[profile_id];
        if profile.component != Component::Orchestrator {
            return Err(Error::invalid("Chat requires an orchestrator profile"));
        }
        let mut values = BTreeMap::new();
        for prompt_id in &profile.prompt_ids {
            for name in &snapshot.configuration.prompts[prompt_id].variables {
                let value = match name.as_str() {
                    "project_id" => project_id,
                    "project_summary" => project_summary,
                    "user_request" => "Follow the user's messages in this conversation.",
                    _ => {
                        return Err(Error::invalid(format!(
                            "Unsupported orchestrator prompt input {name}; use project_id, project_summary, or user_request"
                        )));
                    }
                };
                values.insert(name.clone(), value.into());
            }
        }
        let prompts = snapshot.render_profile(profile_id, &values)?.prompts;
        let mut instructions = prompts
            .iter()
            .map(|prompt| prompt.text.as_str())
            .collect::<Vec<_>>()
            .join("\n\n");
        instructions.push_str("\n\nTask tools are scoped to the active project. Use tools to inspect facts before claiming changes. Agent execution, workflow execution, and repository tools are not implemented yet. You can define and inspect tasks and discuss configured workflows. Do not claim to have run agents, tests, or workflows.");
        TaskTools::definitions(&snapshot.configuration, profile_id)?;
        let conversation = Conversation {
            id: new_id("session"),
            project_id: project_id.into(),
            profile_id: profile_id.into(),
            snapshot_id: snapshot.id,
            model: binding.model,
            provider_id: binding.provider.id,
            title: "New conversation".into(),
            version: 1,
            updated_at: self.now()?,
            state: State::Idle,
            active_run_id: None,
            last_error: None,
            entries: vec![Entry {
                id: new_id("message"),
                message: Message::text(Role::System, instructions),
                call_id: None,
                usage: None,
            }],
        };
        self.db.run("INSERT INTO orchestrator_conversations(id,project_id,version,updated_at,data) VALUES(?1,?2,?3,?4,?5)",
            &[&conversation.id,&conversation.project_id,"1",&conversation.updated_at,&serde_json::to_string(&conversation)?])?;
        Ok(conversation)
    }
    pub fn get(&self, id: &str) -> Result<Conversation> {
        let value = self.db.scalar(
            "SELECT data FROM orchestrator_conversations WHERE id=?1",
            &[id],
        )?;
        Ok(serde_json::from_str(&value)?)
    }
    pub fn list(&self, project_id: &str) -> Result<Vec<Conversation>> {
        self.db.query("SELECT data FROM orchestrator_conversations WHERE project_id=?1 ORDER BY updated_at DESC,id LIMIT 100", &[project_id])?
            .iter().map(|row| Ok(serde_json::from_str(&row[0])?)).collect()
    }
    pub fn save(&self, conversation: &mut Conversation) -> Result<()> {
        let mut next = conversation.clone();
        next.version = next
            .version
            .checked_add(1)
            .filter(|v| *v <= i64::MAX as u64)
            .ok_or_else(|| Error::invalid("Conversation version overflow"))?;
        next.updated_at = self.now()?;
        self.db.run("UPDATE orchestrator_conversations SET version=?1,updated_at=?2,data=?3 WHERE id=?4 AND version=?5", &[
            &next.version.to_string(),&next.updated_at,&serde_json::to_string(&next)?,&next.id,&conversation.version.to_string()])?;
        if self.db.scalar("SELECT changes()", &[])? != "1" {
            return Err(Error::new(
                "VERSION_CONFLICT",
                "Conversation changed; reload it before continuing",
            ));
        }
        *conversation = next;
        Ok(())
    }
    /// Call once at application startup, before accepting commands. Never replays tools.
    pub fn recover_interrupted(&self) -> Result<usize> {
        let rows = self.db.query("SELECT data FROM orchestrator_conversations WHERE json_extract(data,'$.state')='running'", &[])?;
        for row in &rows {
            let mut conversation: Conversation = serde_json::from_str(&row[0])?;
            close_pending(
                &mut conversation,
                "INTERRUPTED",
                "Execution was interrupted and may have performed changes. Inspect task records before retrying.",
            );
            conversation.state = State::Interrupted;
            conversation.active_run_id = None;
            conversation.last_error = Some(Error::new(
                "INTERRUPTED",
                "Previous turn was interrupted; no tools were replayed",
            ));
            self.save(&mut conversation)?;
        }
        Ok(rows.len())
    }
    fn now(&self) -> Result<String> {
        Ok(self
            .db
            .scalar("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')", &[])?)
    }
}

pub(super) fn close_pending(conversation: &mut Conversation, code: &str, message: &str) {
    let answered: HashSet<_> = conversation
        .entries
        .iter()
        .filter_map(|entry| entry.message.tool_call_id.clone())
        .collect();
    let pending = conversation
        .entries
        .iter()
        .flat_map(|entry| entry.message.tool_calls.iter())
        .filter(|call| !answered.contains(&call.id))
        .cloned()
        .collect::<Vec<_>>();
    for call in pending {
        conversation.entries.push(Entry {
            id: new_id("message"),
            message: Message::tool(
                &call.id,
                &json!({"ok":false,"error":{"code":code,"message":message}}),
            ),
            call_id: None,
            usage: None,
        });
    }
}
