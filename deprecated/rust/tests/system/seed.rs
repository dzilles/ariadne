mod fixture;

use ariadne_tasks::task::*;
use std::path::PathBuf;

fn run() -> Result<()> {
    let output = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("tests/system/fixtures/android-chat.sqlite")
        });
    if output.exists() {
        return Err(Error {
            code: "OUTPUT_EXISTS",
            message: format!(
                "{} already exists; choose a new output path",
                output.display()
            ),
        });
    }
    let plan = fixture::read_plan()?;
    if let Some(parent) = output.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    let summary = {
        let mut store = TaskStore::open(&output)?;
        fixture::populate(&mut store, &plan)?
    }; // Closing the final SQLite connection checkpoints WAL into the main file.
    println!("{}", serde_json::to_string_pretty(&summary)?);
    println!("Database: {}", output.display());
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
