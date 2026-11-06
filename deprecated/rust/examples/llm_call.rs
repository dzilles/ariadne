use ariadne_tasks::{Result, configuration::ConfigurationStore, interaction::new_id, llm::*};

fn main() -> Result<()> {
    let root = std::env::args().nth(1).unwrap_or_else(|| ".ariadne".into());
    let profile = std::env::args()
        .nth(2)
        .unwrap_or_else(|| "orchestrator".into());
    let snapshot = ConfigurationStore::open(root)?.create_snapshot()?;
    let binding = Binding::from_snapshot(&snapshot, &profile)?;
    let context = CallContext {
        call_id: new_id("call"),
        caller_id: "llm-example".into(),
        snapshot_id: snapshot.id,
        session_id: None,
        run_id: None,
        task_id: None,
        parent_call_id: None,
    };
    let request = Request {
        messages: vec![Message::text(Role::User, "Say hello in one sentence.")],
        tools: vec![],
    };
    // The orchestrator, an agent runtime, or an LLM-backed tool uses this same API.
    // This example supplies its own input; profile prompt rendering belongs to its caller.
    Gateway::default().generate(
        &binding,
        &request,
        &context,
        &Cancellation::default(),
        &mut |event| {
            if let EventKind::TextDelta { text } = event.kind {
                use std::io::Write;
                print!("{text}");
                std::io::stdout().flush()?;
            }
            Ok(())
        },
    )?;
    println!();
    Ok(())
}
