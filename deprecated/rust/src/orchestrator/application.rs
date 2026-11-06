use super::*;
use crate::{
    Error, Result,
    configuration::ConfigurationStore,
    interaction::{Command, CommandKind, EventContext, EventKind, Interface, Source},
    llm::{Cancellation, Gateway},
    task::{SearchQuery, TaskStore},
};
use std::{
    collections::HashMap,
    fs::{File, OpenOptions},
    path::PathBuf,
    sync::{Arc, Mutex},
    thread,
};

#[derive(Clone)]
pub struct Options {
    pub root: PathBuf,
    pub task_path: PathBuf,
    pub project_id: String,
    pub profile_id: String,
    pub project_summary: String,
}
impl Default for Options {
    fn default() -> Self {
        Self {
            root: ".ariadne".into(),
            task_path: "ariadne.sqlite".into(),
            project_id: "default".into(),
            profile_id: "orchestrator".into(),
            project_summary: "Local project".into(),
        }
    }
}
struct Active {
    run_id: String,
    cancellation: Cancellation,
}
struct AppLock(File);
impl Drop for AppLock {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}
pub struct Application {
    pub options: Options,
    pub interface: Interface,
    gateway: Arc<Gateway>,
    active: Mutex<HashMap<String, Active>>,
    _lock: AppLock,
}
impl Application {
    pub fn start(options: Options, gateway: Arc<Gateway>) -> Result<Arc<Self>> {
        let configuration = ConfigurationStore::open(&options.root)?;
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(options.root.join(".application.lock"))?;
        lock.try_lock().map_err(|_| {
            Error::new(
                "APPLICATION_BUSY",
                "Another chat application is using this configuration directory",
            )
        })?;
        let lock = AppLock(lock);
        let profile = configuration.get_profile(&options.profile_id)?;
        TaskTools::definitions(&configuration.load()?.1, &profile.id)?;
        let store = ConversationStore::open(options.root.join("orchestrator.sqlite"))?;
        store.recover_interrupted()?;
        TaskStore::open(&options.task_path)?;
        let (interface, commands) = Interface::new(128)?;
        let app = Arc::new(Self {
            options,
            interface,
            gateway,
            active: Mutex::new(HashMap::new()),
            _lock: lock,
        });
        let weak = Arc::downgrade(&app);
        thread::spawn(move || {
            while let Ok(command) = commands.recv() {
                let Some(app) = weak.upgrade() else { break };
                app.dispatch(command);
            }
        });
        Ok(app)
    }
    pub fn conversations(&self) -> Result<Vec<Conversation>> {
        ConversationStore::open(self.options.root.join("orchestrator.sqlite"))?
            .list(&self.options.project_id)
    }
    pub fn conversation(&self, id: &str) -> Result<Conversation> {
        let conversation =
            ConversationStore::open(self.options.root.join("orchestrator.sqlite"))?.get(id)?;
        if conversation.project_id != self.options.project_id {
            return Err(Error::new(
                "FORBIDDEN",
                "Conversation belongs to another project",
            ));
        }
        Ok(conversation)
    }
    pub fn create_conversation(&self) -> Result<Conversation> {
        ConversationStore::open(self.options.root.join("orchestrator.sqlite"))?.create(
            &ConfigurationStore::open(&self.options.root)?,
            &self.options.project_id,
            &self.options.profile_id,
            &self.options.project_summary,
        )
    }
    pub fn tasks(&self) -> Result<serde_json::Value> {
        let mut store = TaskStore::open(&self.options.task_path)?;
        Ok(serde_json::to_value(store.orchestrator().search_tasks(
            &SearchQuery {
                project_id: self.options.project_id.clone(),
                text: None,
                status: None,
                tag: None,
                limit: 200,
            },
        )?)?)
    }
    pub fn submit(&self, session: &str, command: CommandKind) -> Result<String> {
        self.conversation(session)?;
        self.interface.submit(session, command)
    }
    fn dispatch(self: &Arc<Self>, command: Command) {
        if let Err(error) = self.conversation(&command.session_id) {
            self.reject(command, error);
            return;
        }
        match command.payload.clone(){
            CommandKind::SendMessage{text}=>{
                let mut active=self.active.lock().unwrap();
                if active.contains_key(&command.session_id){drop(active);self.reject(command,Error::new("BUSY","Wait for this conversation's current turn to finish"));return;}
                if active.len()>=16{drop(active);self.reject(command,Error::new("BUSY","Too many active conversations"));return;}
                let cancellation=Cancellation::default();
                active.insert(command.session_id.clone(),Active{run_id:command.command_id.clone(),cancellation:cancellation.clone()});
                drop(active);
                let app=self.clone();thread::spawn(move ||{
                    let configuration=match ConfigurationStore::open(&app.options.root){Ok(config)=>config,Err(error)=>{app.active.lock().unwrap().remove(&command.session_id);app.reject(command,error.into());return;}};
                    let orchestrator=Orchestrator{configuration,conversation_path:app.options.root.join("orchestrator.sqlite"),task_path:app.options.task_path.clone()};
                    let _=orchestrator.turn(&command.session_id,&command.command_id,&text,&app.gateway,&app.interface,&cancellation);
                    app.active.lock().unwrap().remove(&command.session_id);
                });
            }
            CommandKind::CancelRun{run_id}=>{
                let active=self.active.lock().unwrap();
                if let Some(run)=active.get(&command.session_id).filter(|run|run.run_id==run_id){run.cancellation.cancel();}
                else{drop(active);self.reject(command,Error::new("NOT_FOUND","Run is not active in this conversation"));}
            }
            CommandKind::RespondToInput{..}=>self.reject(command,Error::new("UNSUPPORTED_OPERATION","No workflow input handler is registered yet; send a chat message to the orchestrator")),
        }
    }
    fn reject(self: &Arc<Self>, command: Command, error: Error) {
        let app = self.clone();
        thread::spawn(move || {
            let context = EventContext {
                command_id: Some(command.command_id.clone()),
                run_id: Some(command.command_id),
                ..Default::default()
            };
            let _ = app.interface.publish(
                &command.session_id,
                Source::new("application", "dispatcher"),
                context.clone(),
                EventKind::Error { error },
            );
            let _ = app.interface.publish(
                &command.session_id,
                Source::new("application", "dispatcher"),
                context,
                EventKind::RunFinished {
                    outcome: "rejected".into(),
                },
            );
        });
    }
}
