import copy
from dataclasses import replace
from unittest.mock import patch

from ariadne._util import dumps, loads
from ariadne.task import TaskStore, TaskUpdate, SearchQuery, RecordEvent, DemoEmbedder, EmbeddingModel, EmbeddingOutcome
from ariadne.task.vectors import sync_sources
from tests.support import Case


class TaskCase(Case):
    def setUp(self):
        super().setUp()
        self.store = TaskStore(self.root / "tasks.sqlite")
        self.addCleanup(self.store.close)
        self.api = self.store.orchestrator()
        self.task = self.api.create_task("project", "Build an AI chat application", ["android"])

    def emit(self, event_id, **change):
        return self.store.recorder().record_event(RecordEvent(event_id, self.task.id, change, "run"))


class TaskTests(TaskCase):
    def test_create_edit_search_history_and_version_conflicts(self):
        task = self.api.update_task(self.task.id, description="Build MCP integration", acceptance_criteria=["Supports tools"], expected_version=1)
        self.assertEqual(task.version, 2)
        self.assert_code("CONFLICT", self.api.update_task, task.id, TaskUpdate(tags=[], expected_version=1))
        self.api.add_note(task.id, "Decision: support remote servers")
        self.assertEqual(self.api.search_tasks(SearchQuery("project", text="remote servers"))[0].id, task.id)
        self.assertEqual([e.data["type"] for e in self.api.get_history(task.id)], ["task_created", "task_updated", "note_added"])
        self.assertEqual(self.api.search_tasks(SearchQuery("other")), [])

    def test_dependencies_cannot_cycle_or_cross_projects(self):
        second = self.api.create_task("project", "Second")
        other = self.api.create_task("other", "Other")
        self.api.update_task(second.id, relations=[{"task_id": self.task.id, "kind": "blocked_by"}])
        for target in [second.id, self.task.id, other.id]:
            self.assert_code("VALIDATION_ERROR", self.api.update_task, self.task.id, relations=[{"task_id": target, "kind": "blocked_by"}])

    def test_reference_ids_annotations_and_observations_survive_explicit_replacement(self):
        task = self.api.update_task(self.task.id, files=[{"repository_id": "repo", "path": "app.py"}], links=[{"url": "https://example.com", "comment": "Useful"}])
        file_id, link_id = task.files[0]["id"], task.links[0]["id"]
        self.emit("observed", type="files_observed", files=[{"repository_id": "repo", "path": "app.py", "relation": "modified"}])
        self.api.update_task(task.id, files=[{"repository_id": "repo", "path": "app.py", "comment": "Linked"}], links=[{"url": "https://example.com"}])
        task = self.api.get_task(task.id)
        self.assertEqual(next(r["id"] for r in task.files if r["relation"] == "linked"), file_id)
        self.assertEqual(task.links[0]["id"], link_id)
        observed_id = next(r["id"] for r in task.files if r["relation"] == "modified")
        self.api.annotate_reference(task.id, observed_id, "Runtime observed this")
        task = self.api.update_task(task.id, files=[])
        self.assertEqual(len(task.files), 1)
        self.assertEqual(task.files[0]["comment"], "Runtime observed this")

    def test_bad_paths_line_ranges_and_unknown_update_fields_are_rejected(self):
        for file in [{"path": "../escape"}, {"path": "/absolute"}, {"path": "a", "start_line": 3}, {"path": "a", "start_line": 3, "end_line": 2}]:
            self.assert_code("VALIDATION_ERROR", self.api.update_task, self.task.id, files=[{"repository_id": "repo", **file}])
        self.assert_code("VALIDATION_ERROR", self.api.update_task, self.task.id, {"status": "completed"})
        self.assert_code("VALIDATION_ERROR", self.api.update_task, self.task.id, tags=["x", "x"])

    def test_recording_is_idempotent_and_conflicting_event_ids_roll_back(self):
        first = self.emit("usage", type="usage_recorded", model_call_id="call", input_tokens=10, output_tokens=5)
        self.assertFalse(first.duplicate)
        self.assertTrue(self.emit("usage", type="usage_recorded", model_call_id="call", input_tokens=10, output_tokens=5).duplicate)
        self.emit("same-call", type="usage_recorded", model_call_id="call", input_tokens=10, output_tokens=5)
        self.assertEqual(self.api.get_task(self.task.id).input_tokens, 10)
        before = self.api.get_task(self.task.id).to_dict()
        self.assert_code("CONFLICT", self.emit, "usage", type="usage_recorded", model_call_id="call", input_tokens=11, output_tokens=5)
        self.assert_code("CONFLICT", self.emit, "new-id", type="usage_recorded", model_call_id="call", input_tokens=11, output_tokens=5)
        self.assertEqual(self.api.get_task(self.task.id).to_dict(), before)

    def test_unknown_usage_stays_unknown(self):
        self.emit("one", type="usage_recorded", model_call_id="one", input_tokens=None, output_tokens=5)
        self.emit("two", type="usage_recorded", model_call_id="two", input_tokens=10, output_tokens=7)
        task = self.api.get_task(self.task.id)
        self.assertIsNone(task.input_tokens)
        self.assertEqual(task.output_tokens, 12)

    def test_workflow_order_goal_edits_outcomes_and_restart(self):
        self.assert_code("CONFLICT", self.emit, "out-of-order", type="workflow_status_changed", sequence=2, status="ready")
        self.emit("ready", type="workflow_status_changed", sequence=1, status="ready")
        self.emit("started", type="workflow_status_changed", sequence=2, status="in_progress", current_step="code")
        self.assert_code("TASK_BUSY", self.api.update_task, self.task.id, description="new goal")
        self.emit("done", type="workflow_finished", sequence=3, status="completed", result_summary="Implemented and tested", elapsed_time_ms=50)
        with TaskStore(self.root / "tasks.sqlite") as reopened:
            self.assertEqual(reopened.orchestrator().get_task(self.task.id).elapsed_time_ms, 50)
            reopened.recorder().record_event(RecordEvent("reopen", self.task.id, {"type": "workflow_status_changed", "sequence": 4, "status": "ready"}, "second-run"))
        task = self.api.update_task(self.task.id, description="Changed goal")
        self.assertIsNone(task.result_summary)

    def test_git_development_and_checkpoint_histories_are_distinct(self):
        self.emit("dev", type="git_recorded", reference={"repository_id": "repo", "commit_hash": "abc", "kind": "development"})
        self.assert_code("VALIDATION_ERROR", self.emit, "bad-checkpoint", type="git_recorded", reference={"repository_id": "repo", "commit_hash": "def", "kind": "checkpoint"})
        self.emit("checkpoint", type="git_recorded", reference={"repository_id": "repo", "commit_hash": "def", "kind": "checkpoint", "development_head": "abc"})
        refs = self.api.get_task(self.task.id).git_refs
        self.assertEqual([ref["kind"] for ref in refs], ["development", "checkpoint"])
        self.assertEqual(self.api.get_history(self.task.id)[-1].source, "git_tracker")


class VectorTests(TaskCase):

    def setUp(self):
        super().setUp()
        self.embedder = DemoEmbedder()
        self.store.register_embedding_model(self.embedder.model())

    def test_late_jobs_cannot_publish_stale_vectors_or_ack_current_work(self):
        job = self.store.pending_embeddings(self.embedder.model().id)[0]
        self.api.update_task(self.task.id, description="Build a web search system")
        self.assertEqual(self.store.complete_embedding(job, self.embedder.embed(job.content)), EmbeddingOutcome.OBSOLETE)
        self.assertFalse(self.store.index_status("project").complete)
        current = self.store.pending_embeddings(self.embedder.model().id)[0]
        vector = self.embedder.embed(current.content)
        self.assertEqual(self.store.complete_embedding(current, vector), EmbeddingOutcome.APPLIED)
        self.assertEqual(self.store.complete_embedding(current, vector), EmbeddingOutcome.ALREADY_APPLIED)

    def test_source_removal_and_readdition_never_reuse_revisions(self):
        self.api.update_task(self.task.id, acceptance_criteria=["Support web search"])
        old = next(job for job in self.store.pending_embeddings(self.embedder.model().id) if job.source == "acceptance_criteria")
        self.api.update_task(self.task.id, acceptance_criteria=[])
        self.api.update_task(self.task.id, acceptance_criteria=["Support web search"])
        current = next(job for job in self.store.pending_embeddings(self.embedder.model().id) if job.source == "acceptance_criteria")
        self.assertGreater(current.source_revision, old.source_revision)
        self.assertEqual(self.store.complete_embedding(old, self.embedder.embed(old.content)), EmbeddingOutcome.OBSOLETE)

    def test_metadata_edits_keep_vectors_and_search_uses_current_filters(self):
        self.store.index_pending(self.embedder, 200)
        before = self.store.db.execute("SELECT vector FROM embeddings").fetchall()
        self.api.update_task(self.task.id, tags=["new"])
        self.assertEqual(self.store.db.execute("SELECT vector FROM embeddings").fetchall(), before)
        self.assertEqual(self.store.semantic_search(SearchQuery("project", "chat", tag="android")).hits, [])
        self.assertEqual(self.store.semantic_search(SearchQuery("project", "chat", tag="new")).hits[0].task.id, self.task.id)

    def test_failed_embedder_and_bad_vectors_leave_pending_work_durable(self):
        class Failing(DemoEmbedder):
            def embed(self, value): raise RuntimeError("provider down")
        with self.assertRaises(RuntimeError): self.store.index_pending(Failing(), 200)
        self.assertFalse(self.store.index_status("project").complete)
        job = self.store.pending_embeddings(self.embedder.model().id)[0]
        for vector in [[0.0] * 128, [float("nan")] * 128, [1.0]]:
            self.assert_code("VALIDATION_ERROR", self.store.complete_embedding, job, vector)
        with TaskStore(self.root / "tasks.sqlite") as reopened:
            self.assertTrue(reopened.pending_embeddings(self.embedder.model().id))

    def test_model_spaces_and_project_boundaries_are_isolated(self):
        self.store.index_pending(self.embedder, 200)
        self.store.register_embedding_model(EmbeddingModel("other", 2))
        self.assert_code("CONFLICT", self.store.register_embedding_model, EmbeddingModel("other", 3))
        self.assertTrue(self.store.pending_embeddings("other"))
        self.assertEqual(self.store.semantic_search(SearchQuery("other-project", "chat")).hits, [])
        self.store.rebuild_embeddings()
        self.assertFalse(self.store.index_status("project").complete)

    def test_task_sources_history_and_queue_changes_roll_back_together(self):
        self.store.index_pending(self.embedder, 200)
        before = self.api.get_task(self.task.id).to_dict()
        history_count = len(self.api.get_history(self.task.id))
        original = sync_sources
        def fail(db, task):
            original(db, task)
            raise RuntimeError("injected after source writes")
        with patch("ariadne.task.vectors.sync_sources", fail), self.assertRaises(RuntimeError):
            self.api.update_task(self.task.id, description="Changed source")
        self.assertEqual(self.api.get_task(self.task.id).to_dict(), before)
        self.assertEqual(len(self.api.get_history(self.task.id)), history_count)
        self.assertTrue(self.store.index_status("project").complete)

    def test_vector_publication_and_job_acknowledgement_roll_back_together(self):
        job = self.store.pending_embeddings(self.embedder.model().id)[0]
        self.store.db.execute("CREATE TEMP TRIGGER fail_ack BEFORE DELETE ON embedding_jobs BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        self.assert_code("DATABASE_ERROR", self.store.complete_embedding, job, self.embedder.embed(job.content))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM embeddings").fetchone()[0], 0)
        self.assertTrue(self.store.pending_embeddings(self.embedder.model().id))
