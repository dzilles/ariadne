use ariadne_tasks::configuration::*;
use std::{collections::BTreeMap, path::PathBuf};

fn main() -> Result<()> {
    let root = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(".ariadne"));
    let store = ConfigurationStore::open(&root)?;
    let config: Configuration =
        serde_json::from_str(include_str!("../tests/configuration/fixtures/example.json"))?;
    // Refuse to replace existing configuration when rerunning the initializer.
    let revision = store.replace_configuration(config, Some(0))?;
    let snapshot = store.create_snapshot()?;
    let inputs = BTreeMap::from([
        ("task".into(), "Implement project-scoped task search".into()),
        (
            "project_context".into(),
            "Rust prototype with SQLite task storage".into(),
        ),
        ("findings".into(), "No prior review findings".into()),
    ]);
    println!("Configuration directory: {}", root.display());
    println!("Saved revision: {revision}");
    println!("Snapshot ID: {}", snapshot.id);
    println!(
        "{}",
        serde_json::to_string_pretty(&snapshot.render_profile("coder", &inputs)?)?
    );
    Ok(())
}
