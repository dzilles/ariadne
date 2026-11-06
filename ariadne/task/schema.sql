CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    workflow_sequence INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL
);
CREATE INDEX tasks_project ON tasks(project_id);
CREATE TABLE history (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    run_id TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX history_task ON history(task_id, sequence);
CREATE TABLE recorded_events (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    data TEXT NOT NULL
);
CREATE TABLE usage_calls (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    call_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY(task_id, call_id)
);
CREATE TABLE workflow_outcomes (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    elapsed_ms INTEGER NOT NULL CHECK(elapsed_ms >= 0),
    PRIMARY KEY(task_id, run_id)
);
CREATE TABLE embedding_models (
    id TEXT PRIMARY KEY,
    dimensions INTEGER NOT NULL CHECK(dimensions > 0)
);
CREATE TABLE task_sources (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    content TEXT NOT NULL,
    PRIMARY KEY(task_id, source)
);
CREATE TABLE embedding_jobs (
    task_id TEXT NOT NULL,
    source TEXT NOT NULL,
    model TEXT NOT NULL REFERENCES embedding_models(id),
    source_revision INTEGER NOT NULL,
    PRIMARY KEY(task_id, source, model),
    FOREIGN KEY(task_id, source) REFERENCES task_sources(task_id, source) ON DELETE CASCADE
);
CREATE TABLE embeddings (
    task_id TEXT NOT NULL,
    source TEXT NOT NULL,
    model TEXT NOT NULL REFERENCES embedding_models(id),
    source_revision INTEGER NOT NULL,
    vector TEXT NOT NULL,
    PRIMARY KEY(task_id, source, model),
    FOREIGN KEY(task_id, source) REFERENCES task_sources(task_id, source) ON DELETE CASCADE
);
PRAGMA user_version=1;
