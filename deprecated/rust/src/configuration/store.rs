use super::*;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions, TryLockError},
    io::Write,
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Debug, Clone)]
pub struct ConfigurationStore {
    root: PathBuf,
}

struct WriteLock(File);
impl Drop for WriteLock {
    fn drop(&mut self) {
        // Release explicitly: a concurrently spawned child may briefly inherit
        // the underlying handle before exec, extending its lifetime past close.
        let _ = self.0.unlock();
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PromptLocation {
    file: String,
    variables: Vec<String>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    format_version: u32,
    revision: u64,
    #[serde(default)]
    providers: BTreeMap<String, Provider>,
    prompts: BTreeMap<String, PromptLocation>,
    profiles: BTreeMap<String, Profile>,
    workflows: BTreeMap<String, Workflow>,
}
impl Default for Manifest {
    fn default() -> Self {
        Self {
            format_version: 1,
            revision: 0,
            providers: BTreeMap::new(),
            prompts: BTreeMap::new(),
            profiles: BTreeMap::new(),
            workflows: BTreeMap::new(),
        }
    }
}

impl ConfigurationStore {
    pub fn open(root: impl AsRef<Path>) -> Result<Self> {
        let store = Self {
            root: root.as_ref().to_path_buf(),
        };
        fs::create_dir_all(store.root.join("prompts"))?;
        fs::create_dir_all(store.root.join("snapshots"))?;
        if !store.root.join("config.json").exists() {
            let _lock = store.write_lock()?;
            if !store.root.join("config.json").exists() {
                store.write_manifest(&Manifest::default())?;
            }
        }
        store.load()?;
        Ok(store)
    }

    /// Loads one atomically published manifest and its immutable prompt revisions.
    pub fn load(&self) -> Result<(u64, Configuration)> {
        let manifest = self.manifest()?;
        let config = self.materialize(&manifest)?;
        config.validate()?;
        Ok((manifest.revision, config))
    }

    pub fn status(&self) -> Result<ConfigurationStatus> {
        let (revision, config) = self.load()?;
        Ok(ConfigurationStatus {
            revision,
            providers: config.providers.len(),
            profiles: config.profiles.len(),
            prompts: config.prompts.len(),
            workflows: config.workflows.len(),
        })
    }

    pub fn list_profiles(&self, component: Option<Component>) -> Result<Vec<Profile>> {
        Ok(self
            .load()?
            .1
            .profiles
            .into_values()
            .filter(|profile| component.is_none_or(|c| c == profile.component))
            .collect())
    }
    pub fn get_profile(&self, id: &str) -> Result<Profile> {
        self.load()?
            .1
            .profiles
            .remove(id)
            .ok_or_else(|| missing("Profile", id))
    }
    pub fn list_providers(&self) -> Result<Vec<Provider>> {
        Ok(self.load()?.1.providers.into_values().collect())
    }
    pub fn get_provider(&self, id: &str) -> Result<Provider> {
        self.load()?
            .1
            .providers
            .remove(id)
            .ok_or_else(|| missing("Provider", id))
    }
    pub fn save_provider(&self, provider: Provider, expected_revision: Option<u64>) -> Result<u64> {
        self.edit(expected_revision, |config| {
            config.providers.insert(provider.id.clone(), provider);
        })
    }
    pub fn get_prompt(&self, id: &str) -> Result<Prompt> {
        self.load()?
            .1
            .prompts
            .remove(id)
            .ok_or_else(|| missing("Prompt", id))
    }
    pub fn get_workflow(&self, id: &str) -> Result<Workflow> {
        self.load()?
            .1
            .workflows
            .remove(id)
            .ok_or_else(|| missing("Workflow", id))
    }
    pub fn list_workflows(&self) -> Result<Vec<Workflow>> {
        Ok(self.load()?.1.workflows.into_values().collect())
    }

    pub fn save_prompt(&self, prompt: Prompt, expected_revision: Option<u64>) -> Result<u64> {
        self.edit(expected_revision, |config| {
            config.prompts.insert(prompt.id.clone(), prompt);
        })
    }
    pub fn save_profile(&self, profile: Profile, expected_revision: Option<u64>) -> Result<u64> {
        self.edit(expected_revision, |config| {
            config.profiles.insert(profile.id.clone(), profile);
        })
    }
    pub fn save_workflow(&self, workflow: Workflow, expected_revision: Option<u64>) -> Result<u64> {
        self.edit(expected_revision, |config| {
            config.workflows.insert(workflow.id.clone(), workflow);
        })
    }
    /// Publish coordinated prompt/profile/workflow edits together.
    pub fn replace_configuration(
        &self,
        config: Configuration,
        expected_revision: Option<u64>,
    ) -> Result<u64> {
        self.edit(expected_revision, |current| *current = config)
    }

    fn edit(&self, expected: Option<u64>, update: impl FnOnce(&mut Configuration)) -> Result<u64> {
        let _lock = self.write_lock()?;
        let manifest = self.manifest()?;
        if expected.is_some_and(|revision| revision != manifest.revision) {
            return Err(Error::new(
                "VERSION_CONFLICT",
                format!(
                    "Current configuration revision is {}; reload before editing",
                    manifest.revision
                ),
            ));
        }
        let original = self.materialize(&manifest)?;
        let mut config = original.clone();
        update(&mut config);
        config.validate()?;
        let revision = manifest
            .revision
            .checked_add(1)
            .ok_or_else(|| Error::invalid("Configuration revision overflow"))?;
        let mut locations = BTreeMap::new();
        for (id, prompt) in &config.prompts {
            if original.prompts.get(id) == Some(prompt) {
                locations.insert(id.clone(), manifest.prompts[id].clone());
            } else {
                let filename = format!("{id}-r{revision}-{}.md", unique_token()?);
                let path = self.root.join("prompts").join(&filename);
                let mut file = File::create_new(&path)?;
                file.write_all(prompt.text.as_bytes())?;
                file.sync_all()?;
                locations.insert(
                    id.clone(),
                    PromptLocation {
                        file: format!("prompts/{filename}"),
                        variables: prompt.variables.clone(),
                    },
                );
            }
        }
        sync_directory(&self.root.join("prompts"))?;
        self.write_manifest(&Manifest {
            format_version: 1,
            revision,
            prompts: locations,
            providers: config.providers,
            profiles: config.profiles,
            workflows: config.workflows,
        })?;
        Ok(revision)
    }

    pub fn create_snapshot(&self) -> Result<Snapshot> {
        let (revision, configuration) = self.load()?;
        let snapshot = Snapshot {
            id: format!("snapshot-{revision}-{}", unique_token()?),
            revision,
            configuration,
        };
        let path = self
            .root
            .join("snapshots")
            .join(format!("{}.json", snapshot.id));
        atomic_write(&path, &serde_json::to_vec_pretty(&snapshot)?)?;
        Ok(snapshot)
    }

    pub fn get_snapshot(&self, id: &str) -> Result<Snapshot> {
        validation::identifier(id)?;
        let path = self.root.join("snapshots").join(format!("{id}.json"));
        let bytes = fs::read(path).map_err(|error| {
            if error.kind() == std::io::ErrorKind::NotFound {
                missing("Snapshot", id)
            } else {
                error.into()
            }
        })?;
        let snapshot: Snapshot = serde_json::from_slice(&bytes)?;
        if snapshot.id != id {
            return Err(Error::invalid("Snapshot ID does not match its filename"));
        }
        snapshot.configuration.validate()?;
        Ok(snapshot)
    }

    fn write_lock(&self) -> Result<WriteLock> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.root.join(".write.lock"))?;
        match file.try_lock() {
            Ok(()) => Ok(WriteLock(file)),
            Err(TryLockError::WouldBlock) => Err(Error::new(
                "CONFIGURATION_BUSY",
                "Another configuration editor is saving; retry this operation",
            )),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }

    fn manifest(&self) -> Result<Manifest> {
        let manifest: Manifest = serde_json::from_slice(&fs::read(self.root.join("config.json"))?)?;
        if manifest.format_version != 1 {
            return Err(Error::new(
                "SCHEMA_VERSION",
                "Unsupported configuration format version",
            ));
        }
        Ok(manifest)
    }

    fn materialize(&self, manifest: &Manifest) -> Result<Configuration> {
        let mut prompts = BTreeMap::new();
        for (id, location) in &manifest.prompts {
            validation::identifier(id)?;
            let name = location
                .file
                .strip_prefix("prompts/")
                .ok_or_else(|| Error::invalid("Prompt files must be under prompts/"))?;
            if !name.ends_with(".md")
                || !name[..name.len() - 3]
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
                || name.len() <= 3
            {
                return Err(Error::invalid("Invalid prompt file location"));
            }
            let text = fs::read_to_string(self.root.join("prompts").join(name))?;
            prompts.insert(
                id.clone(),
                Prompt {
                    id: id.clone(),
                    text,
                    variables: location.variables.clone(),
                },
            );
        }
        Ok(Configuration {
            providers: manifest.providers.clone(),
            prompts,
            profiles: manifest.profiles.clone(),
            workflows: manifest.workflows.clone(),
        })
    }

    fn write_manifest(&self, manifest: &Manifest) -> Result<()> {
        atomic_write(
            &self.root.join("config.json"),
            &serde_json::to_vec_pretty(manifest)?,
        )
    }
}

fn missing(kind: &str, id: &str) -> Error {
    Error::new("NOT_FOUND", format!("{kind} {id} does not exist"))
}

fn unique_token() -> Result<String> {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| Error::new("CLOCK_ERROR", error.to_string()))?;
    Ok(format!(
        "{:x}-{:x}-{:x}",
        timestamp.as_nanos(),
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ))
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| Error::invalid("Configuration path has no parent"))?;
    let temporary = parent.join(format!(".config-{}.tmp", unique_token()?));
    let result = (|| -> Result<()> {
        let mut file = File::create_new(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temporary, path)?;
        sync_directory(parent)
    })();
    if result.is_err() {
        let _ = fs::remove_file(temporary);
    }
    result
}

fn sync_directory(path: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        File::open(path)?.sync_all()?;
    }
    #[cfg(not(unix))]
    let _ = path;
    Ok(())
}
