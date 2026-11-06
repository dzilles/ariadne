import json
import subprocess
import sys

from tests.support import Case, ROOT, configuration
from ariadne.configuration import ConfigurationStore


class CliTests(Case):
    def request(self, module, values, *flags):
        result = subprocess.run([sys.executable, "-m", "ariadne", module, *flags], cwd=ROOT,
                                input="\n".join(value if isinstance(value, str) else json.dumps(value) for value in values) + "\n",
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_task_roles_strict_arguments_and_invalid_line_recovery(self):
        flags = ("--db", str(self.root / "tasks.sqlite"))
        result = self.request("task", ["invalid JSON", {"op": "create_task", "project_id": "p", "description": "Task"},
                                     {"op": "record_event", "event": {}}, {"op": "create_task", "project_id": "p", "description": "x", "status": "completed"}], *flags)
        self.assertFalse(result[0]["ok"])
        self.assertEqual(result[1]["result"]["status"], "draft")
        self.assertEqual(result[2]["error"]["code"], "FORBIDDEN")
        self.assertEqual(result[3]["error"]["code"], "VALIDATION_ERROR")
        denied = self.request("task", [{"op": "create_task", "project_id": "p", "description": "no"}], *flags, "--role", "recorder")
        self.assertEqual(denied[0]["error"]["code"], "FORBIDDEN")

    def test_configuration_reader_editor_connections_and_snapshots(self):
        flags = ("--root", str(self.root / "config"))
        replace = {"op": "replace_configuration", "configuration": configuration().to_dict(), "expected_revision": 0}
        self.assertEqual(self.request("config", [replace], *flags)[0]["error"]["code"], "FORBIDDEN")
        self.assertEqual(self.request("config", [replace], *flags, "--role", "editor")[0]["result"]["revision"], 1)
        result = self.request("config", [{"op": "list_providers"}, {"op": "list_profiles", "component": "agent"}, {"op": "create_snapshot"}], *flags)
        self.assertEqual(result[0]["result"][0]["adapter"], "openrouter")
        self.assertEqual(len(result[1]["result"]), 3)
        self.assertTrue(result[2]["result"]["id"].startswith("snapshot-"))

    def test_tool_catalogs_remain_role_limited(self):
        for module, count in [("task", 7), ("config", 4)]:
            result = subprocess.run([sys.executable, "-m", "ariadne", module, "--tools"], cwd=ROOT, capture_output=True, text=True, check=True)
            catalog = json.loads(result.stdout)
            self.assertEqual(len(catalog), count)
            self.assertTrue(all(not tool["name"].startswith(("save_", "record_")) for tool in catalog))
