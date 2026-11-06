import copy

from ariadne._util import FileLock, loads, dumps
from ariadne.configuration import ConfigurationStore, Configuration, Prompt, Profile, Provider
from ariadne.llm import Binding
from tests.support import Case, configuration


class ConfigurationTests(Case):
    def setUp(self):
        super().setUp()
        self.store = ConfigurationStore(self.root / "config")
        self.config = configuration()
        self.store.replace_configuration(self.config, 0)

    def test_profiles_prompts_connections_and_workflows_round_trip(self):
        revision, restored = ConfigurationStore(self.store.root).load()
        self.assertEqual(revision, 1)
        self.assertEqual(restored, self.config)
        self.assertEqual(len(self.store.list_profiles("agent")), 3)
        self.assertEqual(len(self.store.list_providers()), 1)
        self.assertEqual(self.store.get_workflow("code-review-test").max_step_executions, 12)
        self.assert_code("NOT_FOUND", self.store.get_profile, "missing")

    def test_stale_revision_and_simultaneous_editors_are_rejected(self):
        self.store.save_prompt(Prompt("extra", "Hello"), 1)
        self.assert_code("VERSION_CONFLICT", self.store.save_prompt, Prompt("other", "Hi"), 1)
        with FileLock(self.store.root / ".write.lock"):
            self.assert_code("CONFIGURATION_BUSY", self.store.save_prompt, Prompt("locked", "Hello"))
        self.assertEqual(self.store.save_prompt(Prompt("released", "Hello"), 2), 3)

    def test_snapshot_pins_endpoint_model_and_prompt_after_live_edits(self):
        saved = self.store.create_snapshot()
        provider = self.store.get_provider("openrouter")
        provider.base_url = "http://127.0.0.1:9999/api/v1"
        self.store.save_provider(provider)
        profile = self.store.get_profile("orchestrator")
        profile.model = "new/model"
        self.store.save_profile(profile)
        prompt = self.store.get_prompt("orchestrator")
        prompt.text += "\nA new instruction"
        self.store.save_prompt(prompt)
        old = self.store.get_snapshot(saved.id)
        self.assertEqual(old, saved)
        self.assertEqual(Binding.from_snapshot(old, "orchestrator").model, "example/planning-model")
        self.assertEqual(Binding.from_snapshot(old, "orchestrator").provider.base_url, "https://openrouter.ai/api/v1")
        self.assertNotIn("A new instruction", old.configuration.prompts["orchestrator"].text)

    def test_invalid_updates_leave_manifest_and_prompt_files_unchanged(self):
        before = (self.store.root / "config.json").read_bytes()
        files = set((self.store.root / "prompts").iterdir())
        bad = copy.deepcopy(self.config)
        bad.prompts["coder"].text += "{{missing}}"
        self.assert_code("VALIDATION_ERROR", self.store.replace_configuration, bad, 1)
        self.assertEqual((self.store.root / "config.json").read_bytes(), before)
        self.assertEqual(set((self.store.root / "prompts").iterdir()), files)

    def test_prompt_inputs_are_exact_unicode_and_never_recursively_expanded(self):
        self.store.save_prompt(Prompt("literal", "Задача: {{ name }}", ["name"]))
        self.store.save_profile(Profile("greeter", "tool", prompt_ids=["literal"], model="example/model", provider_id="openrouter"))
        config = self.store.load()[1]
        self.assertEqual(config.render_profile("greeter", {"name": "{{literal}}"}).prompts[0].text, "Задача: {{literal}}")
        self.assert_code("VALIDATION_ERROR", config.render_profile, "greeter", {})
        self.assert_code("VALIDATION_ERROR", config.render_profile, "greeter", {"name": "x", "extra": "y"})

    def test_workflow_references_reachability_and_terminal_paths_are_validated(self):
        for mutation in ("missing_agent", "wrong_component", "missing_target", "unreachable", "no_terminal", "missing_inputs", "zero_limit"):
            bad = copy.deepcopy(self.config)
            workflow = bad.workflows["code-review-test"]
            if mutation == "missing_agent": workflow.steps["code"].agent_profile = "missing"
            if mutation == "wrong_component": workflow.steps["code"].agent_profile = "runtime"
            if mutation == "missing_target": workflow.steps["code"].transitions["completed"] = {"kind": "step", "step": "missing"}
            if mutation == "unreachable": workflow.steps["unreachable"] = copy.deepcopy(workflow.steps["test"])
            if mutation == "no_terminal":
                for name, step in workflow.steps.items(): step.transitions = {"repeat": {"kind": "step", "step": name}}
            if mutation == "missing_inputs": workflow.steps["code"].inputs = []
            if mutation == "zero_limit": workflow.max_step_executions = 0
            with self.subTest(mutation=mutation): self.assert_code("VALIDATION_ERROR", bad.validate)

    def test_unsafe_connections_plaintext_credentials_and_bad_limits_are_rejected(self):
        for url in ("http://example.com", "file:///etc/passwd", "https://key@host", "https://host/path?secret=key", "https://host/#x", "https://host/\n"):
            bad = copy.deepcopy(self.config)
            bad.providers["openrouter"].base_url = url
            self.assert_code("VALIDATION_ERROR", bad.validate)
        for key in ("secret-key", "env:", "env:BAD-NAME"):
            bad = copy.deepcopy(self.config)
            bad.providers["openrouter"].credential_ref = key
            self.assert_code("VALIDATION_ERROR", bad.validate)
        for key, value in [("max_tool_calls", True), ("max_output_tokens", 0), ("temperature", 3), ("top_p", -1)]:
            bad = copy.deepcopy(self.config)
            bad.profiles["coder"].settings[key] = value
            self.assert_code("VALIDATION_ERROR", bad.validate)

    def test_missing_connections_duplicate_tools_and_unknown_fields_are_rejected(self):
        bad = copy.deepcopy(self.config)
        bad.profiles["coder"].provider_id = "missing"
        self.assert_code("VALIDATION_ERROR", bad.validate)
        bad = copy.deepcopy(self.config)
        bad.profiles["coder"].tools *= 2
        self.assert_code("VALIDATION_ERROR", bad.validate)
        self.assert_code("VALIDATION_ERROR", Profile.from_dict, {"id": "x", "component": "tool", "api_key": "secret"})
        self.assert_code("VALIDATION_ERROR", self.config.validate_tools, ["read_file"])

    def test_legacy_configurations_and_snapshots_read_without_guessing_connections(self):
        legacy = self.config.to_dict()
        legacy.pop("providers")
        for profile in legacy["profiles"].values():
            profile.pop("provider_id", None)
            if profile["model"]:
                profile["credential_ref"] = "env:LEGACY_KEY"
        self.store.replace_configuration(legacy, 1)
        snapshot = self.store.create_snapshot()
        self.assert_code("VALIDATION_ERROR", Binding.from_snapshot, snapshot, "coder")
        self.assertEqual(self.store.load()[1], Configuration.from_dict(legacy))

    def test_prompt_and_snapshot_paths_cannot_escape_the_root(self):
        manifest_path = self.store.root / "config.json"
        manifest = loads(manifest_path.read_text())
        manifest["prompts"]["coder"]["file"] = "prompts/../../outside.md"
        manifest_path.write_text(dumps(manifest))
        self.assert_code("VALIDATION_ERROR", self.store.load)
        self.assert_code("VALIDATION_ERROR", self.store.get_snapshot, "../outside")

    def test_coordinated_prompt_and_workflow_updates_are_published_together(self):
        changed = copy.deepcopy(self.config)
        changed.prompts["coder"].text += "\n{{acceptance_criteria}}"
        changed.prompts["coder"].variables.append("acceptance_criteria")
        self.assert_code("VALIDATION_ERROR", self.store.save_prompt, changed.prompts["coder"])
        changed.workflows["code-review-test"].steps["code"].inputs.append("acceptance_criteria")
        self.assertEqual(self.store.replace_configuration(changed, 1), 2)
