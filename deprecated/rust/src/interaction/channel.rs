use super::*;
use crate::{Error, Result};
use std::{
    collections::HashMap,
    sync::{
        Arc, Mutex,
        mpsc::{self, Receiver, SyncSender},
    },
    time::Duration,
};

struct Session {
    sequence: u64,
    generation: String,
    sender: Option<SyncSender<Event>>,
}
struct Shared {
    sessions: Mutex<HashMap<String, Arc<Mutex<Session>>>>,
    capacity: usize,
}
#[derive(Clone)]
pub struct Interface {
    shared: Arc<Shared>,
    commands: SyncSender<Command>,
}
pub struct Subscription {
    session: Arc<Mutex<Session>>,
    generation: String,
    receiver: Option<Receiver<Event>>,
}
impl Interface {
    pub fn new(capacity: usize) -> Result<(Self, Receiver<Command>)> {
        if capacity == 0 {
            return Err(Error::invalid("Channel capacity must be positive"));
        }
        let (commands, receiver) = mpsc::sync_channel(capacity);
        Ok((
            Self {
                shared: Arc::new(Shared {
                    sessions: Mutex::new(HashMap::new()),
                    capacity,
                }),
                commands,
            },
            receiver,
        ))
    }
    pub fn submit(&self, session_id: &str, payload: CommandKind) -> Result<String> {
        if session_id.is_empty() {
            return Err(Error::invalid("Command needs a session ID"));
        }
        match &payload {
            CommandKind::SendMessage { text } if text.trim().is_empty() || text.len() > 65536 => {
                return Err(Error::invalid("Message must contain 1 to 65536 bytes"));
            }
            CommandKind::CancelRun { run_id } if run_id.is_empty() => {
                return Err(Error::invalid("Cancellation needs run_id"));
            }
            CommandKind::RespondToInput { request_id, .. } if request_id.is_empty() => {
                return Err(Error::invalid("Input response needs request_id"));
            }
            _ => {}
        }
        let command_id = new_id("command");
        self.commands
            .try_send(Command {
                command_id: command_id.clone(),
                session_id: session_id.into(),
                payload,
            })
            .map_err(|error| match error {
                mpsc::TrySendError::Full(_) => {
                    Error::new("BUSY", "Command queue is full; retry later")
                }
                _ => Error::new("DISCONNECTED", "Command handler is not running"),
            })?;
        Ok(command_id)
    }
    pub fn subscribe(&self, session_id: &str) -> Result<Subscription> {
        if session_id.is_empty() {
            return Err(Error::invalid("Subscription needs session ID"));
        }
        let mut sessions = self
            .shared
            .sessions
            .lock()
            .map_err(|_| Error::new("CHANNEL_ERROR", "Session channel lock failed"))?;
        let slot = sessions
            .entry(session_id.into())
            .or_insert_with(|| {
                Arc::new(Mutex::new(Session {
                    sequence: 0,
                    generation: String::new(),
                    sender: None,
                }))
            })
            .clone();
        drop(sessions);
        let mut session = slot
            .lock()
            .map_err(|_| Error::new("CHANNEL_ERROR", "Session lock failed"))?;
        if session.sender.is_some() {
            return Err(Error::new(
                "ALREADY_SUBSCRIBED",
                "This session already has a UI subscriber",
            ));
        }
        let (sender, receiver) = mpsc::sync_channel(self.shared.capacity);
        session.generation = new_id("subscription");
        session.sender = Some(sender);
        Ok(Subscription {
            session: slot.clone(),
            generation: session.generation.clone(),
            receiver: Some(receiver),
        })
    }
    pub fn publish(
        &self,
        session_id: &str,
        source: Source,
        context: EventContext,
        payload: EventKind,
    ) -> Result<()> {
        let slot = self
            .shared
            .sessions
            .lock()
            .map_err(|_| Error::new("CHANNEL_ERROR", "Session channel lock failed"))?
            .get(session_id)
            .cloned()
            .ok_or_else(|| Error::new("NO_SUBSCRIBER", "No UI is listening to this session"))?;
        let mut session = slot
            .lock()
            .map_err(|_| Error::new("CHANNEL_ERROR", "Session lock failed"))?;
        session.sequence = session
            .sequence
            .checked_add(1)
            .ok_or_else(|| Error::new("CHANNEL_ERROR", "Session sequence overflow"))?;
        let event = Event {
            event_id: new_id("event"),
            session_id: session_id.into(),
            sequence: session.sequence,
            source,
            context,
            payload,
        };
        let Some(sender) = &session.sender else {
            return Err(Error::new(
                "NO_SUBSCRIBER",
                "No UI is listening to this session",
            ));
        };
        // Keep ordering and apply bounded backpressure. Receiver drop unblocks send.
        sender
            .send(event)
            .map_err(|_| Error::new("NO_SUBSCRIBER", "UI subscriber disconnected"))
    }
}
impl Subscription {
    pub fn recv(&self) -> Result<Event> {
        self.receiver
            .as_ref()
            .unwrap()
            .recv()
            .map_err(|_| Error::new("DISCONNECTED", "Event stream closed"))
    }
    pub fn recv_timeout(
        &self,
        timeout: Duration,
    ) -> std::result::Result<Event, mpsc::RecvTimeoutError> {
        self.receiver.as_ref().unwrap().recv_timeout(timeout)
    }
}
impl Drop for Subscription {
    fn drop(&mut self) {
        drop(self.receiver.take());
        if let Ok(mut session) = self.session.lock()
            && session.generation == self.generation
        {
            session.sender = None;
        }
    }
}
