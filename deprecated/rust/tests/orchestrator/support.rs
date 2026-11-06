use ariadne_tasks::{
    Result, configuration::ConfigurationStore, interaction::new_id, llm::*, orchestrator::*,
};
use std::{
    collections::VecDeque,
    path::PathBuf,
    sync::{Arc, Mutex},
};

pub struct Directory(pub PathBuf);
impl Directory {
    pub fn new() -> Self {
        let root = std::env::temp_dir().join(new_id("ariadne-chat-test"));
        std::fs::create_dir(&root).unwrap();
        Self(root)
    }
    pub fn config(&self) -> ConfigurationStore {
        ConfigurationStore::open(self.0.join("config")).unwrap()
    }
    pub fn initialize(&self) {
        ariadne_tasks::orchestrator::cli::initialize(&self.0.join("config"), "example/model")
            .unwrap();
    }
    pub fn conversations(&self) -> ConversationStore {
        ConversationStore::open(self.0.join("orchestrator.sqlite")).unwrap()
    }
    pub fn conversation(&self) -> Conversation {
        self.conversations()
            .create(&self.config(), "project", "orchestrator", "A Rust project")
            .unwrap()
    }
    pub fn engine(&self) -> Orchestrator {
        Orchestrator {
            configuration: self.config(),
            conversation_path: self.0.join("orchestrator.sqlite"),
            task_path: self.0.join("tasks.sqlite"),
        }
    }
    pub fn options(&self) -> Options {
        Options {
            root: self.0.join("config"),
            task_path: self.0.join("tasks.sqlite"),
            project_id: "project".into(),
            profile_id: "orchestrator".into(),
            project_summary: "A Rust project".into(),
        }
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
pub struct Credentials;
impl CredentialResolver for Credentials {
    fn resolve(&self, _: &str) -> Result<String> {
        Ok("mock-key".into())
    }
}
pub struct Script {
    responses: Mutex<VecDeque<Result<Response>>>,
    pub requests: Mutex<Vec<(Binding, Request)>>,
}
impl Script {
    pub fn new(responses: Vec<Result<Response>>) -> Arc<Self> {
        Arc::new(Self {
            responses: Mutex::new(responses.into()),
            requests: Mutex::new(vec![]),
        })
    }
    pub fn gateway(self: &Arc<Self>) -> Gateway {
        let mut gateway = Gateway::new(Arc::new(Credentials));
        gateway.register_adapter("openrouter", self.clone());
        gateway
    }
}
impl Adapter for Script {
    fn generate(
        &self,
        binding: &Binding,
        request: &Request,
        _: &dyn CredentialResolver,
        cancellation: &Cancellation,
        emit: &mut dyn FnMut(EventKind) -> Result<()>,
    ) -> Result<Response> {
        cancellation.check()?;
        self.requests
            .lock()
            .unwrap()
            .push((binding.clone(), request.clone()));
        let response = self
            .responses
            .lock()
            .unwrap()
            .pop_front()
            .expect("Unexpected model call")?;
        if let Some(text) = &response.message.content {
            emit(EventKind::TextDelta { text: text.clone() })?;
        }
        Ok(response)
    }
}
pub fn reply(text: &str) -> Result<Response> {
    Ok(Response {
        message: Message::text(Role::Assistant, text),
        finish_reason: "stop".into(),
        usage: Usage {
            input_tokens: Some(10),
            output_tokens: Some(5),
            cost: None,
        },
        provider_request_id: Some(new_id("generation")),
        model: None,
    })
}
pub fn calls(calls: Vec<(&str, &str, serde_json::Value)>) -> Result<Response> {
    let mut message = Message::text(Role::Assistant, "");
    message.content = None;
    message.tool_calls = calls
        .into_iter()
        .map(|(id, name, args)| ToolCall {
            id: id.into(),
            name: name.into(),
            arguments: args.to_string(),
        })
        .collect();
    Ok(Response {
        message,
        finish_reason: "tool_calls".into(),
        usage: Usage::default(),
        provider_request_id: None,
        model: None,
    })
}
