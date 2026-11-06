use super::support::*;
use ariadne_tasks::{
    Result,
    interaction::{CommandKind, EventKind},
    llm::*,
    orchestrator::Application,
};
use std::{
    sync::{Arc, mpsc},
    time::Duration,
};

struct Stall {
    started: mpsc::Sender<()>,
}
impl Adapter for Stall {
    fn generate(
        &self,
        _: &Binding,
        _: &Request,
        _: &dyn CredentialResolver,
        cancel: &Cancellation,
        _: &mut dyn FnMut(ariadne_tasks::llm::EventKind) -> Result<()>,
    ) -> Result<Response> {
        self.started.send(()).unwrap();
        loop {
            cancel.check()?;
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}
#[test]
fn application_dispatches_commands_cancels_active_turns_and_excludes_another_instance() {
    let directory = Directory::new();
    directory.initialize();
    let (started, ready) = mpsc::channel();
    let mut gateway = Gateway::new(Arc::new(Credentials));
    gateway.register_adapter("openrouter", Arc::new(Stall { started }));
    let app = Application::start(directory.options(), Arc::new(gateway)).unwrap();
    assert_eq!(
        Application::start(directory.options(), Arc::new(Gateway::default()))
            .err()
            .unwrap()
            .code,
        "APPLICATION_BUSY"
    );
    let conversation = app.create_conversation().unwrap();
    let events = app.interface.subscribe(&conversation.id).unwrap();
    let run = app
        .submit(
            &conversation.id,
            CommandKind::SendMessage {
                text: "hello".into(),
            },
        )
        .unwrap();
    ready.recv_timeout(Duration::from_secs(3)).unwrap();
    app.submit(&conversation.id, CommandKind::CancelRun { run_id: run })
        .unwrap();
    loop {
        let event = events.recv_timeout(Duration::from_secs(3)).unwrap();
        if let EventKind::RunFinished { outcome } = event.payload {
            assert_eq!(outcome, "cancelled");
            break;
        }
    }
    let saved = app.conversation(&conversation.id).unwrap();
    assert_eq!(saved.last_error.unwrap().code, "CANCELLED");
    assert!(saved.active_run_id.is_none());
}

#[test]
fn initializer_refuses_to_overwrite_existing_configuration() {
    let directory = Directory::new();
    directory.initialize();
    let before = directory.config().load().unwrap();
    assert_eq!(
        ariadne_tasks::orchestrator::cli::initialize(
            &directory.0.join("config"),
            "different/model"
        )
        .unwrap_err()
        .code,
        "VERSION_CONFLICT"
    );
    assert_eq!(directory.config().load().unwrap(), before);
}
