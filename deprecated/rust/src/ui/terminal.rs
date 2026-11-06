use crate::{
    Result,
    interaction::{CommandKind, EventKind},
    orchestrator::Application,
};
use std::{
    io::{self, BufRead, Write},
    sync::{Arc, mpsc},
    thread,
    time::Duration,
};

pub fn terminal(app: Arc<Application>) -> Result<()> {
    println!(
        "Ariadne · {}\n/new · /sessions · /use ID · /stop · /quit",
        app.options.project_id
    );
    let mut conversation = app
        .conversations()?
        .into_iter()
        .next()
        .map(Ok)
        .unwrap_or_else(|| app.create_conversation())?;
    print_history(&conversation);
    let mut events = app.interface.subscribe(&conversation.id)?;
    let mut active = conversation.active_run_id.clone();
    let mut quitting = false;
    let (input, lines) = mpsc::channel();
    thread::spawn(move || {
        for line in io::stdin().lock().lines() {
            if input.send(line).is_err() {
                break;
            }
        }
    });
    print!("you> ");
    io::stdout().flush()?;
    loop {
        match lines.try_recv() {
            Ok(Ok(line)) => {
                let line = line.trim();
                if line == "/quit" {
                    if let Some(run_id) = active.clone() {
                        let _ = app.submit(&conversation.id, CommandKind::CancelRun { run_id });
                        quitting = true;
                    } else {
                        break;
                    }
                    continue;
                }
                if line == "/stop" {
                    if let Some(run_id) = &active {
                        app.submit(
                            &conversation.id,
                            CommandKind::CancelRun {
                                run_id: run_id.clone(),
                            },
                        )?;
                    }
                    continue;
                }
                if line == "/sessions" {
                    for session in app.conversations()? {
                        println!("{}  {}", session.id, session.title);
                    }
                    continue;
                }
                if line == "/new" || line.starts_with("/use ") {
                    if active.is_some() {
                        println!("Finish or stop the current turn first.");
                        continue;
                    }
                    let next = if line == "/new" {
                        app.create_conversation()
                    } else {
                        app.conversation(line.trim_start_matches("/use "))
                    };
                    match next {
                        Ok(next) => {
                            drop(events);
                            conversation = next;
                            events = app.interface.subscribe(&conversation.id)?;
                            print_history(&conversation);
                        }
                        Err(error) => eprintln!("{error}"),
                    }
                    print!("you> ");
                    io::stdout().flush()?;
                    continue;
                }
                if line.is_empty() {
                    continue;
                }
                if active.is_some() {
                    println!("Wait for the current turn or enter /stop.");
                    continue;
                }
                active = Some(app.submit(
                    &conversation.id,
                    CommandKind::SendMessage { text: line.into() },
                )?);
            }
            Ok(Err(error)) => return Err(error.into()),
            Err(mpsc::TryRecvError::Disconnected) if active.is_none() => break,
            _ => {}
        }
        match events.recv_timeout(Duration::from_millis(40)) {
            Ok(event) => match event.payload {
                EventKind::MessageStarted { .. } => {
                    print!("\nariadne> ");
                    io::stdout().flush()?;
                }
                EventKind::MessageDelta { text, .. } => {
                    print!("{text}");
                    io::stdout().flush()?;
                }
                EventKind::MessageFinished { .. } => println!(),
                EventKind::ActivityUpdated { label, state } => println!("  {label}: {state}"),
                EventKind::Error { error } => eprintln!("\n{error}"),
                EventKind::RunFinished { .. } => {
                    active = None;
                    if quitting {
                        break;
                    }
                    print!("\nyou> ");
                    io::stdout().flush()?;
                }
                _ => {}
            },
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(_) => break,
        }
    }
    Ok(())
}
fn print_history(conversation: &crate::orchestrator::Conversation) {
    println!("\n{} ({})", conversation.title, conversation.id);
    for entry in &conversation.entries {
        let role = match entry.message.role {
            crate::llm::Role::User => "you",
            crate::llm::Role::Assistant => "ariadne",
            _ => continue,
        };
        if let Some(content) = &entry.message.content {
            println!("{role}> {content}");
        }
    }
}
