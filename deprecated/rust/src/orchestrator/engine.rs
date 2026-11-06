use super::{store::close_pending, *};
use crate::{
    Error, Result,
    configuration::ConfigurationStore,
    interaction::{EventContext, EventKind, Interface, Source, new_id},
    llm::{self, Binding, CallContext, Cancellation, Gateway, Message, Request, Role},
    task::{DemoEmbedder, Embedder, TaskStore},
};
use serde_json::json;
use std::path::PathBuf;

pub struct Orchestrator {
    pub configuration: ConfigurationStore,
    pub conversation_path: PathBuf,
    pub task_path: PathBuf,
}
impl Orchestrator {
    pub fn turn(
        &self,
        session_id: &str,
        command_id: &str,
        text: &str,
        gateway: &Gateway,
        interface: &Interface,
        cancellation: &Cancellation,
    ) -> Result<()> {
        let result = self.turn_inner(
            session_id,
            command_id,
            text,
            gateway,
            interface,
            cancellation,
        );
        let context = EventContext {
            command_id: Some(command_id.into()),
            run_id: Some(command_id.into()),
            ..Default::default()
        };
        let source = Source::new("orchestrator", "orchestrator");
        if let Err(error) = &result {
            let _ = interface.publish(
                session_id,
                source.clone(),
                context.clone(),
                EventKind::Error {
                    error: error.clone(),
                },
            );
        }
        let outcome = match &result {
            Ok(()) => "completed",
            Err(error) if error.code == "CANCELLED" => "cancelled",
            _ => "failed",
        };
        let _ = interface.publish(
            session_id,
            source,
            context,
            EventKind::RunFinished {
                outcome: outcome.into(),
            },
        );
        result
    }
    fn turn_inner(
        &self,
        session_id: &str,
        command_id: &str,
        text: &str,
        gateway: &Gateway,
        interface: &Interface,
        cancellation: &Cancellation,
    ) -> Result<()> {
        let store = ConversationStore::open(&self.conversation_path)?;
        let mut conversation = store.get(session_id)?;
        if conversation.state == State::Running {
            return Err(Error::new(
                "BUSY",
                "This conversation already has an active turn",
            ));
        }
        if text.trim().is_empty() || text.len() > 65536 {
            return Err(Error::invalid("Message must contain 1 to 65536 bytes"));
        }
        let context = EventContext {
            command_id: Some(command_id.into()),
            run_id: Some(command_id.into()),
            ..Default::default()
        };
        conversation.state = State::Running;
        conversation.active_run_id = Some(command_id.into());
        conversation.last_error = None;
        if !conversation
            .entries
            .iter()
            .any(|entry| entry.message.role == Role::User)
        {
            conversation.title = text.chars().take(60).collect();
        }
        conversation.entries.push(Entry {
            id: new_id("message"),
            message: Message::text(Role::User, text),
            call_id: None,
            usage: None,
        });
        store.save(&mut conversation)?;
        let result = self.run_turn(
            &store,
            &mut conversation,
            gateway,
            interface,
            &context,
            cancellation,
        );
        conversation.active_run_id = None;
        match &result {
            Ok(()) => conversation.state = State::Idle,
            Err(error) => {
                close_pending(
                    &mut conversation,
                    &error.code,
                    "The turn stopped. Tool execution may have occurred; inspect task records before retrying.",
                );
                conversation.state = State::Failed;
                conversation.last_error = Some(error.clone());
            }
        }
        store.save(&mut conversation)?;
        result
    }

    fn run_turn(
        &self,
        store: &ConversationStore,
        conversation: &mut Conversation,
        gateway: &Gateway,
        interface: &Interface,
        event_context: &EventContext,
        cancellation: &Cancellation,
    ) -> Result<()> {
        let snapshot = self.configuration.get_snapshot(&conversation.snapshot_id)?;
        let binding = Binding::from_snapshot(&snapshot, &conversation.profile_id)?;
        let definitions =
            TaskTools::definitions(&snapshot.configuration, &conversation.profile_id)?;
        let limit = snapshot.configuration.profiles[&conversation.profile_id]
            .settings
            .get("max_tool_calls")
            .and_then(|v| v.as_u64())
            .unwrap_or(12)
            .min(100);
        let mut tasks = TaskStore::open(&self.task_path)?;
        tasks.register_embedding_model(&DemoEmbedder.model())?;
        let source = Source::new("orchestrator", &conversation.profile_id);
        let session_id = conversation.id.clone();
        let mut used = 0;
        for _ in 0..=limit {
            cancellation.check()?;
            let call_id = new_id("call");
            let message_id = new_id("message");
            let mut context = event_context.clone();
            context.call_id = Some(call_id.clone());
            let notify = |payload| {
                let _ = interface.publish(&session_id, source.clone(), context.clone(), payload);
            };
            notify(EventKind::MessageStarted {
                message_id: message_id.clone(),
            });
            let request = Request {
                messages: conversation
                    .entries
                    .iter()
                    .map(|entry| entry.message.clone())
                    .collect(),
                tools: definitions.clone(),
            };
            let call_context = CallContext {
                call_id: call_id.clone(),
                caller_id: conversation.profile_id.clone(),
                snapshot_id: snapshot.id.clone(),
                session_id: Some(conversation.id.clone()),
                run_id: event_context.run_id.clone(),
                task_id: None,
                parent_call_id: None,
            };
            let response = gateway.generate(
                &binding,
                &request,
                &call_context,
                cancellation,
                &mut |event| {
                    if let llm::EventKind::TextDelta { text } = event.kind {
                        notify(EventKind::MessageDelta {
                            message_id: message_id.clone(),
                            text,
                        });
                    }
                    Ok(())
                },
            )?;
            if !matches!(response.finish_reason.as_str(), "stop" | "tool_calls") {
                return Err(Error::new(
                    "INCOMPLETE_RESPONSE",
                    format!("Model stopped with {}", response.finish_reason),
                ));
            }
            let calls = response.message.tool_calls.clone();
            let text = response.message.content.clone().unwrap_or_default();
            if calls.is_empty() && text.trim().is_empty() {
                return Err(Error::new("EMPTY_RESPONSE", "Model returned no reply"));
            }
            let previous_ids = conversation
                .entries
                .iter()
                .flat_map(|entry| entry.message.tool_calls.iter())
                .map(|call| call.id.as_str())
                .collect::<std::collections::HashSet<_>>();
            if calls
                .iter()
                .any(|call| previous_ids.contains(call.id.as_str()))
            {
                return Err(Error::new(
                    "PROTOCOL_ERROR",
                    "Model reused a previous tool-call ID",
                ));
            }
            conversation.entries.push(Entry {
                id: message_id.clone(),
                message: response.message,
                call_id: Some(call_id),
                usage: Some(response.usage),
            });
            // Journal the model's requests before executing any side effects.
            store.save(conversation)?;
            notify(EventKind::MessageFinished { message_id, text });
            if calls.is_empty() {
                return Ok(());
            }
            for call in calls {
                cancellation.check()?;
                if used >= limit {
                    return Err(Error::new(
                        "TOOL_LIMIT",
                        "Orchestrator tool-call limit reached",
                    ));
                }
                used += 1;
                notify(EventKind::ActivityUpdated {
                    label: call.name.clone(),
                    state: "running".into(),
                });
                let result = serde_json::from_str(&call.arguments)
                    .map_err(Error::from)
                    .and_then(|arguments| {
                        TaskTools {
                            store: &mut tasks,
                            configuration: &snapshot.configuration,
                            project_id: &conversation.project_id,
                            profile_id: &conversation.profile_id,
                        }
                        .call(&call.name, arguments)
                    });
                let (value, state) = match result {
                    Ok(value) => (json!({"ok":true,"result":value}), "completed"),
                    Err(error) => (json!({"ok":false,"error":error}), "failed"),
                };
                conversation.entries.push(Entry {
                    id: new_id("message"),
                    message: Message::tool(&call.id, &value),
                    call_id: None,
                    usage: None,
                });
                store.save(conversation)?;
                notify(EventKind::ActivityUpdated {
                    label: call.name,
                    state: state.into(),
                });
            }
        }
        Err(Error::new("TOOL_LIMIT", "Orchestrator round limit reached"))
    }
}
