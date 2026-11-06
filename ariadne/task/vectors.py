from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import re
from typing import Protocol

from ariadne._util import JsonModel, transaction, text, integer, finite, dumps, loads
from ariadne.errors import Error
from .model import Task, TaskSummary, SearchQuery


@dataclass(frozen=True)
class EmbeddingModel(JsonModel):
    id: str
    dimensions: int


class Embedder(Protocol):
    def model(self) -> EmbeddingModel: ...
    def embed(self, text: str) -> list[float]: ...


class DemoEmbedder:
    """Offline token hashing, not learned semantic embeddings. Compatible with Rust v1."""

    def model(self):
        return EmbeddingModel("demo-token-hash-v1", 128)

    def embed(self, text):
        vector = [0.0] * 128
        for token in filter(None, re.split(r"[\W_]+", text.lower())):
            value = 0xCBF29CE484222325
            for byte in token.encode("utf-8"):
                value = ((value ^ byte) * 0x100000001B3) & (2**64 - 1)
            vector[value % 128] += 1.0
        validate_vector(vector, 128)
        return vector


@dataclass
class EmbeddingJob(JsonModel):
    task_id: str
    source: str
    source_revision: int
    content: str
    model: EmbeddingModel


class EmbeddingOutcome(StrEnum):
    APPLIED = "applied"
    OBSOLETE = "obsolete"
    ALREADY_APPLIED = "already_applied"


@dataclass
class IndexProgress(JsonModel):
    applied: int = 0
    obsolete: int = 0
    already_applied: int = 0


@dataclass
class IndexStatus(JsonModel):
    sources: int
    ready: int
    pending: int
    complete: bool


@dataclass
class SemanticHit(JsonModel):
    task: TaskSummary
    score: float
    source: str


@dataclass
class SemanticResults(JsonModel):
    hits: list[SemanticHit]
    index: IndexStatus
    model: EmbeddingModel


def sync_sources(db, task):
    desired = {"description": task.description}
    if task.acceptance_criteria:
        desired["acceptance_criteria"] = "\n".join(task.acceptance_criteria)
    if task.result_summary and task.result_summary.strip():
        desired["result_summary"] = task.result_summary
    current = dict(db.execute("SELECT source,content FROM task_sources WHERE task_id=?", (task.id,)))
    for source in current.keys() - desired.keys():
        db.execute("DELETE FROM task_sources WHERE task_id=? AND source=?", (task.id, source))
    for source, content in desired.items():
        if current.get(source) == content:
            continue
        db.execute("INSERT INTO task_sources VALUES(?,?,?,?) ON CONFLICT(task_id,source) DO UPDATE SET revision=excluded.revision,content=excluded.content", (task.id, source, task.version, content))
        db.execute("DELETE FROM embeddings WHERE task_id=? AND source=?", (task.id, source))
        db.execute("INSERT INTO embedding_jobs SELECT ?,?,id,? FROM embedding_models WHERE 1 ON CONFLICT(task_id,source,model) DO UPDATE SET source_revision=excluded.source_revision", (task.id, source, task.version))


def model_dimensions(db, model):
    row = db.execute("SELECT dimensions FROM embedding_models WHERE id=?", (model,)).fetchone()
    if row is None:
        raise Error("NOT_FOUND", "Embedding model is not registered")
    return row[0]


def enqueue_missing(db, model):
    db.execute("""INSERT INTO embedding_jobs SELECT s.task_id,s.source,?,s.revision FROM task_sources s
        WHERE NOT EXISTS(SELECT 1 FROM embeddings e WHERE e.task_id=s.task_id AND e.source=s.source AND e.model=? AND e.source_revision=s.revision)
        ON CONFLICT(task_id,source,model) DO UPDATE SET source_revision=excluded.source_revision""", (model, model))


def register_model(store, model):
    text(model.id, "embedding model ID")
    integer(model.dimensions, "embedding dimensions", 1, 8192)
    with transaction(store.db):
        row = store.db.execute("SELECT dimensions FROM embedding_models WHERE id=?", (model.id,)).fetchone()
        if row and row[0] != model.dimensions:
            raise Error("CONFLICT", "Use a new model/version ID for different dimensions")
        store.db.execute("INSERT OR IGNORE INTO embedding_models VALUES(?,?)", (model.id, model.dimensions))
        enqueue_missing(store.db, model.id)


def pending_embeddings(store, model, limit=20):
    integer(limit, "limit", 1, 200)
    dimensions = model_dimensions(store.db, model)
    rows = store.db.execute("""SELECT j.task_id,j.source,j.source_revision,s.content FROM embedding_jobs j
        JOIN task_sources s ON s.task_id=j.task_id AND s.source=j.source AND s.revision=j.source_revision
        WHERE j.model=? ORDER BY j.task_id,j.source LIMIT ?""", (model, limit))
    return [EmbeddingJob(*tuple(row), EmbeddingModel(model, dimensions)) for row in rows]


def validate_vector(vector, dimensions):
    if not isinstance(vector, (list, tuple)) or len(vector) != dimensions or not vector:
        raise Error.invalid("Embedding has the wrong dimension")
    for value in vector:
        finite(value, "embedding value")
    if not any(value != 0 for value in vector):
        raise Error.invalid("Embedding must have nonzero magnitude")


def complete_embedding(store, job, vector):
    validate_vector(vector, job.model.dimensions)
    with transaction(store.db):
        if model_dimensions(store.db, job.model.id) != job.model.dimensions:
            raise Error("CONFLICT", "Embedding model dimension mismatch")
        source = store.db.execute("SELECT revision,content FROM task_sources WHERE task_id=? AND source=?", (job.task_id, job.source)).fetchone()
        if source is None or source[0] != job.source_revision:
            return EmbeddingOutcome.OBSOLETE
        if source[1] != job.content:
            raise Error("CONFLICT", "Embedding job content does not match its revision")
        key = (job.task_id, job.source, job.model.id)
        pending = store.db.execute("SELECT source_revision FROM embedding_jobs WHERE task_id=? AND source=? AND model=?", key).fetchone()
        if pending is None:
            ready = store.db.execute("SELECT 1 FROM embeddings WHERE task_id=? AND source=? AND model=? AND source_revision=?", (*key, job.source_revision)).fetchone()
            return EmbeddingOutcome.ALREADY_APPLIED if ready else EmbeddingOutcome.OBSOLETE
        if pending[0] != job.source_revision:
            return EmbeddingOutcome.OBSOLETE
        store.db.execute("INSERT INTO embeddings VALUES(?,?,?,?,?) ON CONFLICT(task_id,source,model) DO UPDATE SET source_revision=excluded.source_revision,vector=excluded.vector", (*key, job.source_revision, dumps(vector)))
        store.db.execute("DELETE FROM embedding_jobs WHERE task_id=? AND source=? AND model=? AND source_revision=?", (*key, job.source_revision))
        return EmbeddingOutcome.APPLIED


def index_pending(store, embedder, limit):
    model = embedder.model()
    store.register_embedding_model(model)
    jobs = pending_embeddings(store, model.id, limit)
    progress = IndexProgress()
    for job in jobs:
        # Computation deliberately occurs outside the publication transaction.
        outcome = complete_embedding(store, job, embedder.embed(job.content))
        setattr(progress, outcome.value, getattr(progress, outcome.value) + 1)
    return progress


def index_status(store, project_id, model):
    model_dimensions(store.db, model)
    row = store.db.execute("""SELECT
        (SELECT count(*) FROM task_sources s JOIN tasks t ON t.id=s.task_id WHERE t.project_id=?1),
        (SELECT count(*) FROM embeddings e JOIN task_sources s ON s.task_id=e.task_id AND s.source=e.source AND s.revision=e.source_revision JOIN tasks t ON t.id=s.task_id WHERE t.project_id=?1 AND e.model=?2),
        (SELECT count(*) FROM embedding_jobs j JOIN tasks t ON t.id=j.task_id WHERE t.project_id=?1 AND j.model=?2)""", (project_id, model)).fetchone()
    return IndexStatus(*row, row[0] == row[1] and row[2] == 0)


def rebuild_embeddings(store, model):
    with transaction(store.db):
        model_dimensions(store.db, model)
        store.db.execute("DELETE FROM embeddings WHERE model=?", (model,))
        enqueue_missing(store.db, model)


def semantic_search(store, query, embedder):
    from .store import matches_filters
    query = SearchQuery.from_dict(query) if isinstance(query, dict) else query
    query.validate()
    text(query.text, "semantic query text")
    model, vector = embedder.model(), embedder.embed(query.text)
    validate_vector(vector, model.dimensions)
    with transaction(store.db):
        if model_dimensions(store.db, model.id) != model.dimensions:
            raise Error("CONFLICT", "Query embedder differs from the registered model")
        rows = store.db.execute("""SELECT t.data,s.source,e.vector FROM embeddings e
            JOIN task_sources s ON s.task_id=e.task_id AND s.source=e.source AND s.revision=e.source_revision
            JOIN tasks t ON t.id=s.task_id WHERE t.project_id=? AND e.model=?""", (query.project_id, model.id))
        best = {}
        for row in rows:
            task = Task.from_dict(loads(row[0]))
            if not matches_filters(task, query):
                continue
            candidate = loads(row[2])
            validate_vector(candidate, model.dimensions)
            # Scaling avoids overflow with otherwise finite large vectors.
            a, b = unit(vector), unit(candidate)
            score = max(-1.0, min(1.0, math.fsum(x * y for x, y in zip(a, b))))
            hit = SemanticHit(TaskSummary.of(task), score, row[1])
            if task.id not in best or score > best[task.id].score:
                best[task.id] = hit
        hits = sorted(best.values(), key=lambda hit: (-hit.score, hit.task.id))[:query.limit]
        return SemanticResults(hits, index_status(store, query.project_id, model.id), model)


def unit(vector):
    scale = max(abs(v) for v in vector)
    scaled = [v / scale for v in vector]
    norm = math.sqrt(math.fsum(v * v for v in scaled))
    return [v / norm for v in scaled]
