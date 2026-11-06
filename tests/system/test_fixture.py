from collections import Counter
import hashlib
import shutil
import sqlite3

from ariadne._util import loads
from ariadne.task import TaskStore, SearchQuery, TaskUpdate
from ariadne.task.fixtures import seed_database, validate_plan
from tests.support import Case, FIXTURE, PLAN


class FixtureTests(Case):
    def copied_store(self):
        output = self.root / "copied.sqlite"
        shutil.copy2(FIXTURE, output)
        store = TaskStore(output)
        self.addCleanup(store.close)
        return store

    def test_existing_rust_database_has_expected_tasks_graph_and_metadata(self):
        digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        store = self.copied_store()
        tasks = store.orchestrator().search_tasks(SearchQuery("android-ai-chat", limit=200))
        self.assertEqual(len(tasks), 30)
        full = [store.orchestrator().get_task(task.id) for task in tasks]
        self.assertEqual(Counter(t.status for t in full), {"completed": 6, "ready": 4, "in_progress": 1, "blocked": 1, "draft": 18})
        self.assertEqual(sum(r["kind"] == "blocked_by" for t in full for r in t.relations), 64)
        self.assertEqual(store.index_status("android-ai-chat").ready, 66)
        self.assertTrue(store.index_status("android-ai-chat").complete)
        self.assertEqual(store.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), digest)

    def test_existing_vectors_return_the_same_android_search_results(self):
        store = self.copied_store()
        result = store.semantic_search(SearchQuery("android-ai-chat", "internet search citations", tag="search", limit=3))
        self.assertEqual([hit.task.tags[0] for hit in result.hits], ["APP-023", "APP-021", "APP-020"])
        self.assertAlmostEqual(result.hits[0].score, 0.531, places=3)
        self.assertTrue(result.index.complete)
        keyword = store.orchestrator().search_tasks(SearchQuery("android-ai-chat", "MCP", limit=200))
        self.assertGreater(len(keyword), 5)

    def test_python_regenerates_the_full_connected_fixture_from_the_plan(self):
        output = self.root / "generated.sqlite"
        summary = seed_database(output, PLAN)
        self.assertEqual(summary, {"project_id": "android-ai-chat", "tasks": 30, "dependency_edges": 64, "indexed_sources": 66})
        self.assert_code("OUTPUT_EXISTS", seed_database, output, PLAN)
        with TaskStore(output) as store:
            result = store.semantic_search(SearchQuery("android-ai-chat", "internet search citations", tag="search", limit=3))
            self.assertEqual([hit.task.tags[0] for hit in result.hits], ["APP-023", "APP-021", "APP-020"])
            self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_plan_validation_rejects_cycles_and_premature_active_tasks(self):
        plan = loads(PLAN.read_text())
        plan["tasks"][1]["blocked_by"] = [plan["tasks"][2]["key"]]
        self.assert_code("INVALID_FIXTURE", validate_plan, plan)
        plan = loads(PLAN.read_text())
        plan["tasks"][0]["state"] = "draft"
        self.assert_code("INVALID_FIXTURE", validate_plan, plan)

    def test_invalid_plan_is_rejected_before_creating_a_database(self):
        for malformed in ({}, {"project_id": "p", "repository_id": "r", "tasks": [None]}):
            self.assert_code("INVALID_FIXTURE", validate_plan, malformed)
        plan = loads(PLAN.read_text())
        plan["tasks"][-1]["state"] = "unknown"
        path = self.root / "invalid-plan.json"
        from ariadne._util import dumps
        path.write_text(dumps(plan))
        output = self.root / "must-not-exist.sqlite"
        self.assert_code("INVALID_FIXTURE", seed_database, output, path)
        self.assertFalse(output.exists())
