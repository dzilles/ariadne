import copy
from pathlib import Path
import re

from ariadne._util import (FileLock, atomic_write, sync_directory, identifier, integer,
                           object_fields, dumps, loads, new_id)
from ariadne.errors import Error
from .model import Configuration, Prompt, Profile, Provider, Workflow, Snapshot, ConfigurationStatus


class ConfigurationStore:
    def __init__(self, root=".ariadne"):
        self.root = Path(root)
        (self.root / "prompts").mkdir(parents=True, exist_ok=True)
        (self.root / "snapshots").mkdir(exist_ok=True)
        if not (self.root / "config.json").exists():
            with self._lock():
                if not (self.root / "config.json").exists():
                    atomic_write(self.root / "config.json", dumps({"format_version": 1, "revision": 0, "providers": {}, "prompts": {}, "profiles": {}, "workflows": {}}, pretty=True))
        self.load()

    @classmethod
    def open(cls, root=".ariadne"):
        return cls(root)

    def _lock(self):
        return FileLock(self.root / ".write.lock", "CONFIGURATION_BUSY")

    def _manifest(self):
        manifest = object_fields(loads((self.root / "config.json").read_text()), ["format_version", "revision", "prompts", "profiles", "workflows"], ["providers"])
        if type(manifest["format_version"]) is not int or manifest["format_version"] != 1:
            raise Error("SCHEMA_VERSION", "Unsupported configuration format")
        integer(manifest["revision"], "configuration revision")
        return manifest

    def _materialize(self, manifest):
        prompts = {}
        if not isinstance(manifest["prompts"], dict):
            raise Error.invalid("Prompt locations must be an object")
        for key, location in manifest["prompts"].items():
            identifier(key)
            object_fields(location, ["file", "variables"])
            filename = location["file"]
            if not isinstance(filename, str) or not re.fullmatch(r"prompts/[A-Za-z0-9_-]+\.md", filename):
                raise Error.invalid("Prompt locations must be simple Markdown filenames under prompts/")
            prompts[key] = {"id": key, "text": (self.root / filename).read_text(encoding="utf-8"), "variables": location["variables"]}
        config = Configuration.from_dict({"prompts": prompts, "profiles": manifest["profiles"], "workflows": manifest["workflows"], "providers": manifest.get("providers", {})})
        config.validate()
        return config

    def load(self):
        manifest = self._manifest()
        return manifest["revision"], self._materialize(manifest)

    def status(self):
        revision, config = self.load()
        return ConfigurationStatus(revision, len(config.providers), len(config.profiles), len(config.prompts), len(config.workflows))

    def _get(self, group, record_id):
        from ariadne._util import text
        text(record_id, "record ID")
        record = getattr(self.load()[1], group).get(record_id)
        if record is None:
            raise Error("NOT_FOUND", f"{group}: {record_id} does not exist")
        return record

    def get_prompt(self, record_id): return self._get("prompts", record_id)
    def get_profile(self, record_id): return self._get("profiles", record_id)
    def get_provider(self, record_id): return self._get("providers", record_id)
    def get_workflow(self, record_id): return self._get("workflows", record_id)

    def list_profiles(self, component=None):
        from .model import Component
        from ariadne._util import enum_value
        if component is not None:
            enum_value(component, Component, "component")
        return [p for p in self.load()[1].profiles.values() if component is None or p.component == component]

    def list_providers(self): return list(self.load()[1].providers.values())
    def list_workflows(self): return list(self.load()[1].workflows.values())

    def _save(self, group, record, cls, expected_revision):
        record = cls.from_dict(record.to_dict() if isinstance(record, cls) else record)
        return self._edit(lambda config: getattr(config, group).__setitem__(record.id, record), expected_revision)

    def save_prompt(self, prompt, expected_revision=None): return self._save("prompts", prompt, Prompt, expected_revision)
    def save_profile(self, profile, expected_revision=None): return self._save("profiles", profile, Profile, expected_revision)
    def save_provider(self, provider, expected_revision=None): return self._save("providers", provider, Provider, expected_revision)
    def save_workflow(self, workflow, expected_revision=None): return self._save("workflows", workflow, Workflow, expected_revision)

    def replace_configuration(self, configuration, expected_revision=None):
        config = Configuration.from_dict(configuration.to_dict() if isinstance(configuration, Configuration) else configuration)
        return self._edit(lambda _: config, expected_revision)

    def _edit(self, update, expected):
        if expected is not None:
            integer(expected, "expected_revision")
        with self._lock():
            manifest = self._manifest()
            if expected is not None and expected != manifest["revision"]:
                raise Error("VERSION_CONFLICT", f"Current configuration revision is {manifest['revision']}")
            original = self._materialize(manifest)
            candidate = copy.deepcopy(original)
            result = update(candidate)
            if isinstance(result, Configuration):
                candidate = result
            candidate.validate()
            revision = integer(manifest["revision"] + 1, "configuration revision")
            locations = {}
            for key, prompt in candidate.prompts.items():
                if original.prompts.get(key) == prompt:
                    locations[key] = manifest["prompts"][key]
                else:
                    filename = f"prompts/{key}-r{revision}-{new_id()}.md"
                    # New prompt revisions are never overwritten by subsequent saves.
                    import os
                    with open(self.root / filename, "x", encoding="utf-8") as stream:
                        stream.write(prompt.text)
                        stream.flush()
                        os.fsync(stream.fileno())
                    locations[key] = {"file": filename, "variables": prompt.variables}
            sync_directory(self.root / "prompts")
            document = {"format_version": 1, "revision": revision, "prompts": locations,
                        "providers": candidate.providers, "profiles": candidate.profiles, "workflows": candidate.workflows}
            atomic_write(self.root / "config.json", dumps(document, pretty=True))
            return revision

    def create_snapshot(self):
        revision, config = self.load()
        snapshot = Snapshot(f"snapshot-{revision}-{new_id()}", revision, config)
        atomic_write(self.root / "snapshots" / f"{snapshot.id}.json", dumps(snapshot, pretty=True))
        return snapshot

    def get_snapshot(self, record_id):
        identifier(record_id)
        try:
            snapshot = Snapshot.from_dict(loads((self.root / "snapshots" / f"{record_id}.json").read_text()))
        except FileNotFoundError as exc:
            raise Error("NOT_FOUND", f"Snapshot {record_id} does not exist") from exc
        if snapshot.id != record_id:
            raise Error.invalid("Snapshot ID does not match its filename")
        integer(snapshot.revision, "snapshot revision")
        snapshot.configuration.validate()
        return snapshot
