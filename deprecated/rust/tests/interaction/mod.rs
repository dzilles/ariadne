use ariadne_tasks::interaction::*;
use std::{sync::mpsc, thread, time::Duration};

fn publish(interface: &Interface, session: &str, label: &str) {
    interface
        .publish(
            session,
            Source::new("tool", label),
            EventContext::default(),
            EventKind::ActivityUpdated {
                label: label.into(),
                state: "running".into(),
            },
        )
        .unwrap();
}
#[test]
fn concurrent_publishers_are_ordered_and_sessions_are_isolated() {
    let (interface, _) = Interface::new(32).unwrap();
    let a = interface.subscribe("a").unwrap();
    let b = interface.subscribe("b").unwrap();
    let workers = (0..4)
        .map(|n| {
            let interface = interface.clone();
            thread::spawn(move || {
                for _ in 0..5 {
                    publish(&interface, "a", &n.to_string());
                }
            })
        })
        .collect::<Vec<_>>();
    publish(&interface, "b", "other");
    assert_eq!(b.recv().unwrap().sequence, 1);
    for n in 1..=20 {
        let event = a.recv().unwrap();
        assert_eq!(event.sequence, n);
        assert_eq!(event.session_id, "a");
    }
    for worker in workers {
        worker.join().unwrap();
    }
}
#[test]
fn backpressure_unblocks_on_drop_and_does_not_block_another_session() {
    let (interface, _) = Interface::new(1).unwrap();
    let a = interface.subscribe("a").unwrap();
    let b = interface.subscribe("b").unwrap();
    publish(&interface, "a", "first");
    let worker_interface = interface.clone();
    let (sender, receiver) = mpsc::channel();
    let worker = thread::spawn(move || {
        let result = worker_interface.publish(
            "a",
            Source::new("agent", "coder"),
            EventContext::default(),
            EventKind::RunFinished {
                outcome: "completed".into(),
            },
        );
        sender.send(result).unwrap();
    });
    assert!(receiver.recv_timeout(Duration::from_millis(80)).is_err());
    publish(&interface, "b", "independent");
    assert_eq!(b.recv().unwrap().session_id, "b");
    drop(a);
    assert_eq!(
        receiver
            .recv_timeout(Duration::from_secs(1))
            .unwrap()
            .unwrap_err()
            .code,
        "NO_SUBSCRIBER"
    );
    worker.join().unwrap();
    let fresh = interface.subscribe("a").unwrap();
    publish(&interface, "a", "fresh");
    assert_eq!(fresh.recv().unwrap().sequence, 3);
}
#[test]
fn command_submission_validation_and_subscription_ownership_are_explicit() {
    let (interface, commands) = Interface::new(1).unwrap();
    let stream = interface.subscribe("session").unwrap();
    assert_eq!(
        interface.subscribe("session").err().unwrap().code,
        "ALREADY_SUBSCRIBED"
    );
    let id = interface
        .submit(
            "session",
            CommandKind::SendMessage {
                text: "hello".into(),
            },
        )
        .unwrap();
    assert_eq!(
        interface
            .submit(
                "session",
                CommandKind::SendMessage {
                    text: "full".into()
                }
            )
            .unwrap_err()
            .code,
        "BUSY"
    );
    assert_eq!(commands.recv().unwrap().command_id, id);
    assert!(
        interface
            .submit("session", CommandKind::SendMessage { text: " ".into() })
            .is_err()
    );
    drop(stream);
    assert!(interface.subscribe("session").is_ok());
}
