use super::support::*;
use ariadne_tasks::llm::Binding;
use serde_json::{Value, json};

#[test]
fn connections_roundtrip_and_snapshots_keep_model_endpoint_and_credential_references() {
    let directory = Directory::new();
    let store = directory.store();
    store
        .replace_configuration(configuration(), Some(0))
        .unwrap();
    let snapshot = store.create_snapshot().unwrap();
    let original = Binding::from_snapshot(&snapshot, "orchestrator").unwrap();
    assert_eq!(store.status().unwrap().providers, 1);
    assert_eq!(store.list_providers().unwrap().len(), 1);
    let mut connection = store.get_provider("openrouter").unwrap();
    connection.base_url = "http://127.0.0.1:9999/api/v1".into();
    store.save_provider(connection, Some(1)).unwrap();
    let binding =
        Binding::from_snapshot(&store.get_snapshot(&snapshot.id).unwrap(), "orchestrator").unwrap();
    assert_eq!(binding.provider.base_url, original.provider.base_url);
    assert_eq!(binding.provider.credential_ref, "env:OPENROUTER_API_KEY");
    assert_eq!(
        Binding::from_snapshot(&store.create_snapshot().unwrap(), "orchestrator")
            .unwrap()
            .provider
            .base_url,
        "http://127.0.0.1:9999/api/v1"
    );
}

#[test]
fn missing_connections_plain_secrets_unsafe_urls_and_invalid_generation_settings_are_rejected() {
    let mut config = configuration();
    config.profiles.get_mut("coder").unwrap().provider_id = Some("missing".into());
    assert!(config.validate().is_err());
    for credential in ["sk-plaintext-key", "env:", "env:BAD-NAME", "env:KEY\n"] {
        let mut config = configuration();
        config
            .providers
            .get_mut("openrouter")
            .unwrap()
            .credential_ref = credential.into();
        assert!(config.validate().is_err());
    }
    for url in [
        "http://example.com/v1",
        "file:///etc/passwd",
        "https://key@host/v1",
        "https://host/v1?key=secret",
        "https://host/v1\nheader",
        "https://host/v1#fragment",
    ] {
        let mut config = configuration();
        config.providers.get_mut("openrouter").unwrap().base_url = url.into();
        assert!(config.validate().is_err(), "{url}");
    }
    for (key, value) in [
        ("temperature", json!(3)),
        ("top_p", json!(-1)),
        ("max_output_tokens", json!(0)),
    ] {
        let mut config = configuration();
        config
            .profiles
            .get_mut("coder")
            .unwrap()
            .settings
            .insert(key.into(), value);
        assert!(config.validate().is_err());
    }
    let mut config = configuration();
    config.profiles.get_mut("coder").unwrap().credential_ref = Some("env:OTHER_KEY".into());
    assert!(config.validate().is_err());
}

#[test]
fn legacy_manifests_and_snapshots_stay_readable_but_need_an_explicit_connection_to_run() {
    let directory = Directory::new();
    let store = directory.store();
    let mut config = configuration();
    config.providers.clear();
    for profile in config.profiles.values_mut() {
        if profile.model.is_some() {
            profile.provider_id = None;
            profile.credential_ref = Some("env:LEGACY_KEY".into());
        }
    }
    store
        .replace_configuration(config.clone(), Some(0))
        .unwrap();
    let manifest_path = directory.0.join("config.json");
    let mut manifest: Value =
        serde_json::from_slice(&std::fs::read(&manifest_path).unwrap()).unwrap();
    manifest.as_object_mut().unwrap().remove("providers");
    std::fs::write(manifest_path, manifest.to_string()).unwrap();
    assert_eq!(directory.store().load().unwrap().1, config);
    let snapshot = store.create_snapshot().unwrap();
    assert_eq!(
        Binding::from_snapshot(&snapshot, "coder").unwrap_err().code,
        "VALIDATION_ERROR"
    );
    let path = directory
        .0
        .join("snapshots")
        .join(format!("{}.json", snapshot.id));
    let mut old: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    old["configuration"]
        .as_object_mut()
        .unwrap()
        .remove("providers");
    std::fs::write(path, old.to_string()).unwrap();
    assert_eq!(
        store.get_snapshot(&snapshot.id).unwrap().configuration,
        config
    );
}
