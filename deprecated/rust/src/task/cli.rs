use super::tools::{Request, Role, execute, tool_definitions};
use super::*;
use serde_json::json;
use std::io::{self, BufRead, Write};

pub fn run() -> Result<()> {
    let mut path = "ariadne.sqlite".to_string();
    let mut role = Role::Orchestrator;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--db" => path = args.next().ok_or_else(|| invalid("--db needs a path"))?,
            "--role" => {
                role = match args.next().as_deref() {
                    Some("orchestrator") => Role::Orchestrator,
                    Some("recorder") => Role::Recorder,
                    Some("indexer") => Role::Indexer,
                    _ => return Err(invalid("--role must be orchestrator, recorder, or indexer")),
                }
            }
            "--tools" => {
                println!("{}", serde_json::to_string_pretty(&tool_definitions())?);
                return Ok(());
            }
            "--help" | "-h" => {
                println!(
                    "ariadne-tasks [--db PATH] [--role orchestrator|recorder|indexer]\nRead one JSON request per line; emit one JSON response per line.\n--tools prints orchestrator tool schemas.\nVector demo: deterministic token hashing, not learned semantic embeddings."
                );
                return Ok(());
            }
            _ => return Err(invalid(&format!("Unknown argument {arg}; use --help"))),
        }
    }
    let mut store = TaskStore::open(path)?;
    store.register_embedding_model(&DemoEmbedder.model())?;
    let mut output = io::BufWriter::new(io::stdout().lock());
    for line in io::stdin().lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let result = serde_json::from_str::<Request>(&line)
            .map_err(Error::from)
            .and_then(|request| execute(&mut store, role, request));
        let response = match result {
            Ok(result) => json!({"ok":true,"result":result}),
            Err(error) => json!({"ok":false,"error":error}),
        };
        writeln!(output, "{}", serde_json::to_string(&response)?)?;
        output.flush()?;
    }
    Ok(())
}

fn invalid(message: &str) -> Error {
    Error {
        code: "VALIDATION_ERROR",
        message: message.into(),
    }
}
