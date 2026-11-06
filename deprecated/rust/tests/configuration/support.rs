use ariadne_tasks::configuration::*;
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::atomic::{AtomicUsize, Ordering},
};

pub struct Directory(pub PathBuf);
impl Directory {
    pub fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let path = std::env::temp_dir().join(format!(
            "ariadne-config-test-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
    pub fn store(&self) -> ConfigurationStore {
        ConfigurationStore::open(&self.0).unwrap()
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
pub fn configuration() -> Configuration {
    serde_json::from_str(include_str!("fixtures/example.json")).unwrap()
}
pub fn coder_inputs() -> BTreeMap<String, String> {
    BTreeMap::from([
        ("task".into(), "Implement task search".into()),
        ("project_context".into(), "Rust and SQLite".into()),
        ("findings".into(), "No prior findings".into()),
    ])
}
