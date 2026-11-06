import sqlite3
import logging
import json
from typing import List

from src.ariadne.work_items.models import (
    AgentRun,
    AgentRunFinalization,
    AgentRunStatus,
    ArtifactLink,
    Comment,
    ContextEntry,
    GateStatus,
    ToolLogEntry,
    WorkItem,
    WorkItemRelationship,
    WorkItemRelationshipType,
    WorkItemStatus,
    WorkItemStatusHistory,
    WorkItemStore,
    WorkItemType,
)

logger = logging.getLogger(__name__)


class SQLiteWorkItemStore(WorkItemStore):
    """
    Concrete WorkItemStore implementation backed by a local SQLite database.
    """

    def __init__(self, db_path: str = "ariadne_tickets.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Initialize the database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Keep table names stable for existing local databases.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL,
                    type TEXT NOT NULL,
                    priority TEXT,
                    gate_analysis_status TEXT DEFAULT 'Pending',
                    gate_design_status TEXT DEFAULT 'Pending',
                    gate_test_status TEXT DEFAULT 'Pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    commit_hashes TEXT DEFAULT '[]',
                    tool_logs TEXT DEFAULT '[]',
                    shared_context TEXT DEFAULT '',
                    target_branch TEXT DEFAULT '',
                    feature_branch TEXT DEFAULT '',
                    base_commit TEXT DEFAULT '',
                    merge_request_id TEXT DEFAULT '',
                    blocked_reason TEXT DEFAULT '',
                    resumable_status TEXT DEFAULT ''
                )
            """)
            self._ensure_ticket_column(cursor, "updated_at", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "commit_hashes", "TEXT DEFAULT '[]'")
            self._ensure_ticket_column(cursor, "tool_logs", "TEXT DEFAULT '[]'")
            self._ensure_ticket_column(cursor, "shared_context", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "target_branch", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "feature_branch", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "base_commit", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "merge_request_id", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "blocked_reason", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "resumable_status", "TEXT DEFAULT ''")
            cursor.execute(
                """
                UPDATE tickets
                SET updated_at = COALESCE(NULLIF(created_at, ''), CURRENT_TIMESTAMP)
                WHERE updated_at IS NULL OR updated_at = ''
                """
            )

            # Comments Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    author TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticket_id) REFERENCES tickets (id)
                )
            """)

            # Artifacts Table (Links)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    artifact_type TEXT DEFAULT 'link',
                    agent_run_id INTEGER,
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticket_id) REFERENCES tickets (id),
                    FOREIGN KEY (agent_run_id) REFERENCES agent_runs (id)
                )
            """)
            self._ensure_artifact_column(cursor, "artifact_type", "TEXT DEFAULT 'link'")
            self._ensure_artifact_column(cursor, "agent_run_id", "INTEGER")
            self._ensure_artifact_column(cursor, "metadata", "TEXT DEFAULT '{}'")

            # Assignees Table (Many-to-Many or simple list for now)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS assignees (
                    ticket_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    FOREIGN KEY (ticket_id) REFERENCES tickets (id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    agent_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    task_description TEXT DEFAULT '',
                    completion_payload TEXT DEFAULT '{}',
                    evidence TEXT DEFAULT '{}',
                    entry_status TEXT DEFAULT '',
                    exit_status TEXT DEFAULT '',
                    raw_response TEXT DEFAULT '',
                    diagnostics TEXT DEFAULT '{}',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT DEFAULT '',
                    FOREIGN KEY (ticket_id) REFERENCES tickets (id)
                )
            """)
            self._ensure_agent_run_column(cursor, "entry_status", "TEXT DEFAULT ''")
            self._ensure_agent_run_column(cursor, "exit_status", "TEXT DEFAULT ''")
            self._ensure_agent_run_column(cursor, "raw_response", "TEXT DEFAULT ''")
            self._ensure_agent_run_column(cursor, "diagnostics", "TEXT DEFAULT '{}'")
            self._reconcile_duplicate_running_runs(cursor)
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_running_ticket
                ON agent_runs (ticket_id)
                WHERE status = 'RUNNING'
                """
            )

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS context_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    author TEXT NOT NULL,
                    kind TEXT DEFAULT 'note',
                    content TEXT NOT NULL,
                    agent_run_id INTEGER,
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticket_id) REFERENCES tickets (id),
                    FOREIGN KEY (agent_run_id) REFERENCES agent_runs (id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS work_item_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_ticket_id INTEGER NOT NULL,
                    target_ticket_id INTEGER NOT NULL,
                    relationship_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_ticket_id, target_ticket_id, relationship_type),
                    FOREIGN KEY (source_ticket_id) REFERENCES tickets (id),
                    FOREIGN KEY (target_ticket_id) REFERENCES tickets (id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS work_item_status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    from_status TEXT DEFAULT '',
                    to_status TEXT NOT NULL,
                    reason TEXT DEFAULT '',
                    agent_run_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticket_id) REFERENCES tickets (id),
                    FOREIGN KEY (agent_run_id) REFERENCES agent_runs (id)
                )
            """)
            cursor.execute(
                """
                INSERT INTO work_item_status_history (
                    ticket_id, from_status, to_status, reason
                )
                SELECT tickets.id, '', tickets.status, 'Schema history baseline'
                FROM tickets
                WHERE NOT EXISTS (
                    SELECT 1 FROM work_item_status_history
                    WHERE work_item_status_history.ticket_id = tickets.id
                )
                """
            )

            conn.commit()

    def _reconcile_duplicate_running_runs(self, cursor: sqlite3.Cursor) -> None:
        """Close legacy duplicate runs before adding the unique running index."""
        cursor.execute(
            """
            SELECT ticket_id, MAX(id) AS keep_id
            FROM agent_runs
            WHERE status = ?
            GROUP BY ticket_id
            HAVING COUNT(*) > 1
            """,
            (AgentRunStatus.RUNNING.value,),
        )
        for ticket_id, keep_id in cursor.fetchall():
            diagnostics = json.dumps(
                {
                    "failure_kind": "migration",
                    "error_type": "DuplicateRunningAgentRun",
                    "error_message": (
                        "Closed during migration because a newer RUNNING run exists."
                    ),
                },
                sort_keys=True,
            )
            cursor.execute(
                """
                UPDATE agent_runs
                SET status = ?,
                    exit_status = entry_status,
                    diagnostics = ?,
                    finished_at = CURRENT_TIMESTAMP
                WHERE ticket_id = ? AND status = ? AND id <> ?
                """,
                (
                    AgentRunStatus.FAILED.value,
                    diagnostics,
                    ticket_id,
                    AgentRunStatus.RUNNING.value,
                    keep_id,
                ),
            )

    def _ensure_ticket_column(
        self, cursor: sqlite3.Cursor, column_name: str, definition: str
    ) -> None:
        cursor.execute("PRAGMA table_info(tickets)")
        columns = {row[1] for row in cursor.fetchall()}
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE tickets ADD COLUMN {column_name} {definition}")

    def _ensure_artifact_column(
        self, cursor: sqlite3.Cursor, column_name: str, definition: str
    ) -> None:
        cursor.execute("PRAGMA table_info(artifacts)")
        columns = {row[1] for row in cursor.fetchall()}
        if column_name not in columns:
            cursor.execute(
                f"ALTER TABLE artifacts ADD COLUMN {column_name} {definition}"
            )

    def _ensure_agent_run_column(
        self, cursor: sqlite3.Cursor, column_name: str, definition: str
    ) -> None:
        cursor.execute("PRAGMA table_info(agent_runs)")
        columns = {row[1] for row in cursor.fetchall()}
        if column_name not in columns:
            cursor.execute(
                f"ALTER TABLE agent_runs ADD COLUMN {column_name} {definition}"
            )

    def _touch_work_item(self, cursor: sqlite3.Cursor, work_item_id: str) -> None:
        cursor.execute(
            "UPDATE tickets SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (work_item_id,),
        )

    def _parse_json_list(self, raw_json: str | None, field_name: str) -> list:
        if not raw_json:
            return []
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid %s JSON in work item row; returning empty list.", field_name
            )
            return []
        if not isinstance(parsed, list):
            return []

        return parsed

    def _parse_commit_hashes(self, raw_hashes: str | None) -> List[str]:
        return [
            str(commit_hash)
            for commit_hash in self._parse_json_list(raw_hashes, "commit_hashes")
        ]

    def _parse_tool_logs(self, raw_logs: str | None) -> List[ToolLogEntry]:
        entries = []
        for raw_entry in self._parse_json_list(raw_logs, "tool_logs"):
            if not isinstance(raw_entry, dict):
                continue
            try:
                entries.append(ToolLogEntry(**raw_entry))
            except Exception:
                logger.warning(
                    "Invalid tool log entry in work item row; skipping entry."
                )
        return entries

    def _parse_json_object(self, raw_json: str | None, field_name: str) -> dict:
        if not raw_json:
            return {}
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning(
                "Invalid %s JSON in work item row; returning empty dict.", field_name
            )
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def create_work_item(
        self, title: str, description: str, type: WorkItemType, priority: str
    ) -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tickets (title, description, status, type, priority) VALUES (?, ?, ?, ?, ?)",
                (
                    title,
                    description,
                    WorkItemStatus.BACKLOG.value,
                    type.value,
                    priority,
                ),
            )
            ticket_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO work_item_status_history (
                    ticket_id, from_status, to_status, reason
                ) VALUES (?, '', ?, 'Work item created')
                """,
                (ticket_id, WorkItemStatus.BACKLOG.value),
            )
            conn.commit()
            return str(ticket_id)

    def get_work_item(self, work_item_id: str) -> WorkItem:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Fetch work item.
            cursor.execute("SELECT * FROM tickets WHERE id = ?", (work_item_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Work item {work_item_id} not found.")

            # Fetch Comments
            cursor.execute(
                "SELECT * FROM comments WHERE ticket_id = ? ORDER BY created_at ASC",
                (work_item_id,),
            )
            comment_rows = cursor.fetchall()
            comments = [
                Comment(
                    id=str(r["id"]),
                    text=r["text"],
                    author=r["author"],
                    created_at=r["created_at"],
                )
                for r in comment_rows
            ]

            # Fetch Artifacts
            cursor.execute(
                "SELECT * FROM artifacts WHERE ticket_id = ?", (work_item_id,)
            )
            artifact_rows = cursor.fetchall()
            artifacts = [
                ArtifactLink(
                    id=str(r["id"]),
                    title=r["title"],
                    url=r["url"],
                    type=r["artifact_type"] or "link",
                    agent_run_id=str(r["agent_run_id"] or ""),
                    created_at=r["created_at"] or "",
                    metadata=self._parse_json_object(
                        r["metadata"], "artifact_metadata"
                    ),
                )
                for r in artifact_rows
            ]

            # Fetch Assignees
            cursor.execute(
                "SELECT name FROM assignees WHERE ticket_id = ?", (work_item_id,)
            )
            assignee_rows = cursor.fetchall()
            assignees = [r["name"] for r in assignee_rows]

            return WorkItem(
                id=str(row["id"]),
                title=row["title"],
                description=row["description"] or "",
                status=row["status"],
                type=WorkItemType(row["type"]),
                priority=row["priority"] or "Medium",
                assignees=assignees,
                comments=comments,
                artifacts=artifacts,
                created_at=row["created_at"] or "",
                updated_at=row["updated_at"] or "",
                commit_hashes=self._parse_commit_hashes(row["commit_hashes"]),
                tool_logs=self._parse_tool_logs(row["tool_logs"]),
                shared_context=row["shared_context"] or "",
                target_branch=row["target_branch"] or "",
                feature_branch=row["feature_branch"] or "",
                base_commit=row["base_commit"] or "",
                merge_request_id=row["merge_request_id"] or "",
                blocked_reason=row["blocked_reason"] or "",
                resumable_status=row["resumable_status"] or "",
                gate_analysis_status=GateStatus(row["gate_analysis_status"]),
                gate_design_status=GateStatus(row["gate_design_status"]),
                gate_test_status=GateStatus(row["gate_test_status"]),
            )

    def search_work_items(self, query: str) -> List[WorkItem]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM tickets WHERE title LIKE ? OR description LIKE ?",
                (f"%{query}%", f"%{query}%"),
            )
            rows = cursor.fetchall()
            return [self.get_work_item(str(r["id"])) for r in rows]

    def update_status(self, work_item_id: str, status: WorkItemStatus) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM tickets WHERE id = ?", (work_item_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Work item {work_item_id} not found.")
            previous_status = row[0] or ""
            cursor.execute(
                """
                UPDATE tickets
                SET status = ?,
                    blocked_reason = CASE WHEN ? = 'Blocked' THEN blocked_reason ELSE '' END,
                    resumable_status = CASE WHEN ? = 'Blocked' THEN resumable_status ELSE '' END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status.value, status.value, status.value, work_item_id),
            )
            if previous_status != status.value:
                self._record_status_transition(
                    cursor,
                    work_item_id,
                    previous_status,
                    status.value,
                    reason="Manual status update",
                )
            conn.commit()

    def _record_status_transition(
        self,
        cursor: sqlite3.Cursor,
        work_item_id: str,
        from_status: str,
        to_status: str,
        *,
        reason: str = "",
        agent_run_id: str | None = None,
    ) -> None:
        if from_status == to_status:
            return
        cursor.execute(
            """
            INSERT INTO work_item_status_history (
                ticket_id, from_status, to_status, reason, agent_run_id
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (work_item_id, from_status, to_status, reason, agent_run_id),
        )

    def update_description(self, work_item_id: str, description: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tickets SET description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (description, work_item_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Work item {work_item_id} not found.")
            conn.commit()

    def post_comment(self, work_item_id: str, text: str) -> None:
        # For local DB, we can use 'System' or current user as author
        author = "Ariadne"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO comments (ticket_id, text, author) VALUES (?, ?, ?)",
                (work_item_id, text, author),
            )
            self._touch_work_item(cursor, work_item_id)
            conn.commit()

    def set_gate_status(self, work_item_id: str, gate: str, status: GateStatus) -> None:
        gate_col = f"gate_{gate.lower()}_status"
        # Validate column to prevent injection (though gate is controlled by Enum/Internal logic)
        if gate_col not in [
            "gate_analysis_status",
            "gate_design_status",
            "gate_test_status",
        ]:
            raise ValueError(f"Invalid gate name: {gate}")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE tickets SET {gate_col} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status.value, work_item_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Work item {work_item_id} not found.")
            conn.commit()

    def add_artifact_link(
        self,
        work_item_id: str,
        title: str,
        url: str,
        comment: str = None,
        artifact_type: str = "link",
        agent_run_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        title = title.strip()
        url = url.strip()
        artifact_type = artifact_type.strip() or "link"
        if not title:
            raise ValueError("Artifact title cannot be empty.")
        if not url:
            raise ValueError("Artifact URL cannot be empty.")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id FROM artifacts
                WHERE ticket_id = ? AND title = ? AND url = ?
                """,
                (work_item_id, title, url),
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    """
                    UPDATE artifacts
                    SET artifact_type = ?,
                        agent_run_id = ?,
                        metadata = ?
                    WHERE id = ?
                    """,
                    (
                        artifact_type,
                        agent_run_id,
                        json.dumps(metadata or {}, sort_keys=True),
                        existing[0],
                    ),
                )
                self._touch_work_item(cursor, work_item_id)
                conn.commit()
                if comment:
                    self.post_comment(work_item_id, comment)
                return

            cursor.execute(
                """
                INSERT INTO artifacts (
                    ticket_id, title, url, artifact_type, agent_run_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    work_item_id,
                    title,
                    url,
                    artifact_type,
                    agent_run_id,
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )
            self._touch_work_item(cursor, work_item_id)
            conn.commit()
            if comment:
                self.post_comment(work_item_id, comment)

    def delete_artifact_link(
        self,
        work_item_id: str,
        title: str | None = None,
        url: str | None = None,
    ) -> None:
        conditions = ["ticket_id = ?"]
        values = [work_item_id]
        if title is not None:
            conditions.append("title = ?")
            values.append(title)
        if url is not None:
            conditions.append("url = ?")
            values.append(url)
        if len(conditions) == 1:
            raise ValueError("A title or URL is required to delete a link.")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"DELETE FROM artifacts WHERE {' AND '.join(conditions)}",
                values,
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"No matching artifact link found for work item {work_item_id}."
                )
            self._touch_work_item(cursor, work_item_id)
            conn.commit()

    def remove_comment(self, work_item_id: str, comment_id: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM comments WHERE ticket_id = ? AND id = ?",
                (work_item_id, comment_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Comment {comment_id} was not found on work item {work_item_id}."
                )
            self._touch_work_item(cursor, work_item_id)
            conn.commit()

    def add_commit_hash(self, work_item_id: str, commit_hash: str) -> None:
        commit_hash = commit_hash.strip()
        if not commit_hash:
            raise ValueError("Commit hash cannot be empty.")

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT commit_hashes FROM tickets WHERE id = ?", (work_item_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Work item {work_item_id} not found.")

            hashes = self._parse_commit_hashes(row["commit_hashes"])
            if commit_hash not in hashes:
                hashes.append(commit_hash)
                cursor.execute(
                    "UPDATE tickets SET commit_hashes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(hashes), work_item_id),
                )
            conn.commit()

    def append_shared_context(
        self,
        work_item_id: str,
        author: str,
        context: str,
        agent_run_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        context = context.strip()
        if not context:
            raise ValueError("Shared context cannot be empty.")

        entry = f"[{author.strip() or 'Ariadne'}]\n{context}"
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT shared_context FROM tickets WHERE id = ?", (work_item_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Work item {work_item_id} not found.")

            existing_context = row["shared_context"] or ""
            new_context = f"{existing_context.rstrip()}\n\n{entry}".strip()
            cursor.execute(
                "UPDATE tickets SET shared_context = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_context, work_item_id),
            )
            cursor.execute(
                """
                INSERT INTO context_entries (
                    ticket_id, author, kind, content, agent_run_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    work_item_id,
                    author.strip() or "Ariadne",
                    "handoff",
                    context,
                    agent_run_id,
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )
            conn.commit()

    def add_context_entry(
        self,
        work_item_id: str,
        author: str,
        content: str,
        kind: str = "note",
        agent_run_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        author = author.strip() or "Ariadne"
        content = content.strip()
        kind = kind.strip() or "note"
        if not content:
            raise ValueError("Context entry content cannot be empty.")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM tickets WHERE id = ?", (work_item_id,))
            if not cursor.fetchone():
                raise ValueError(f"Work item {work_item_id} not found.")
            cursor.execute(
                """
                INSERT INTO context_entries (
                    ticket_id, author, kind, content, agent_run_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    work_item_id,
                    author,
                    kind,
                    content,
                    agent_run_id,
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )
            self._touch_work_item(cursor, work_item_id)
            conn.commit()
            return str(cursor.lastrowid)

    def list_context_entries(
        self, work_item_id: str, limit: int | None = None
    ) -> List[ContextEntry]:
        query = "SELECT * FROM context_entries WHERE ticket_id = ? ORDER BY created_at ASC, id ASC"
        values: list = [work_item_id]
        if limit is not None:
            query += " LIMIT ?"
            values.append(max(1, int(limit)))

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, values)
            rows = cursor.fetchall()
            return [
                ContextEntry(
                    id=str(row["id"]),
                    work_item_id=str(row["ticket_id"]),
                    author=row["author"],
                    kind=row["kind"] or "note",
                    content=row["content"],
                    agent_run_id=str(row["agent_run_id"] or ""),
                    created_at=row["created_at"] or "",
                    metadata=self._parse_json_object(row["metadata"], "metadata"),
                )
                for row in rows
            ]

    def start_agent_run(
        self,
        work_item_id: str,
        agent_name: str,
        task_description: str,
    ) -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, status FROM tickets WHERE id = ?", (work_item_id,)
            )
            work_item = cursor.fetchone()
            if not work_item:
                raise ValueError(f"Work item {work_item_id} not found.")

            try:
                cursor.execute(
                    """
                    INSERT INTO agent_runs (
                        ticket_id, agent_name, status, task_description, entry_status
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        work_item_id,
                        agent_name,
                        AgentRunStatus.RUNNING.value,
                        task_description,
                        work_item[1] or "",
                    ),
                )
            except sqlite3.IntegrityError as error:
                cursor.execute(
                    """
                    SELECT id, agent_name FROM agent_runs
                    WHERE ticket_id = ? AND status = ?
                    """,
                    (work_item_id, AgentRunStatus.RUNNING.value),
                )
                running = cursor.fetchone()
                if running:
                    raise ValueError(
                        f"Work item {work_item_id} already has RUNNING agent run "
                        f"#{running[0]} ({running[1]})."
                    ) from error
                raise
            self._touch_work_item(cursor, work_item_id)
            conn.commit()
            return str(cursor.lastrowid)

    def get_running_agent_run(self, work_item_id: str) -> AgentRun | None:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM agent_runs
                WHERE ticket_id = ? AND status = ?
                ORDER BY id DESC LIMIT 1
                """,
                (work_item_id, AgentRunStatus.RUNNING.value),
            )
            row = cursor.fetchone()
            return self._agent_run_from_row(row) if row else None

    def finish_agent_run(
        self,
        agent_run_id: str,
        status: AgentRunStatus,
        completion_payload: dict,
        evidence: dict,
        exit_status: str = "",
        raw_response: str = "",
        diagnostics: dict | None = None,
    ) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT agent_runs.ticket_id, tickets.status
                FROM agent_runs
                JOIN tickets ON tickets.id = agent_runs.ticket_id
                WHERE agent_runs.id = ?
                """,
                (agent_run_id,),
            )
            run = cursor.fetchone()
            if not run:
                raise ValueError(f"Agent run {agent_run_id} not found.")
            resolved_exit_status = exit_status or run[1] or ""
            cursor.execute(
                """
                UPDATE agent_runs
                SET status = ?,
                    completion_payload = ?,
                    evidence = ?,
                    exit_status = ?,
                    raw_response = ?,
                    diagnostics = ?,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    status.value,
                    json.dumps(completion_payload, sort_keys=True),
                    json.dumps(evidence, sort_keys=True),
                    resolved_exit_status,
                    raw_response,
                    json.dumps(diagnostics or {}, sort_keys=True),
                    agent_run_id,
                ),
            )
            self._touch_work_item(cursor, str(run[0]))
            conn.commit()

    def finalize_agent_run(
        self,
        agent_run_id: str,
        finalization: AgentRunFinalization,
    ) -> None:
        """Atomically apply the terminal run record and resulting ticket changes."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                SELECT agent_runs.*, tickets.status AS ticket_status,
                       tickets.commit_hashes, tickets.shared_context
                FROM agent_runs
                JOIN tickets ON tickets.id = agent_runs.ticket_id
                WHERE agent_runs.id = ?
                """,
                (agent_run_id,),
            )
            run = cursor.fetchone()
            if not run:
                raise ValueError(f"Agent run {agent_run_id} not found.")
            if run["status"] != AgentRunStatus.RUNNING.value:
                raise ValueError(
                    f"Agent run {agent_run_id} is already {run['status']}; "
                    "only RUNNING runs can be finalized."
                )

            work_item_id = str(run["ticket_id"])
            current_status = run["ticket_status"] or ""
            entry_status = run["entry_status"] or current_status
            if current_status != entry_status:
                raise ValueError(
                    f"Work item {work_item_id} changed from agent-run entry status "
                    f"'{entry_status}' to '{current_status}'; refusing stale finalization."
                )
            target_status = self._final_status(
                finalization,
                entry_status=entry_status,
                current_status=current_status,
            )
            if finalization.exit_status and finalization.exit_status != target_status:
                raise ValueError(
                    f"Finalization exit status '{finalization.exit_status}' does not "
                    f"match resulting work-item status '{target_status}'."
                )
            exit_status = target_status
            completion_payload = finalization.completion.model_dump(
                mode="json",
                exclude_none=True,
            )

            cursor.execute(
                """
                UPDATE agent_runs
                SET status = ?, completion_payload = ?, evidence = ?,
                    exit_status = ?, raw_response = ?, diagnostics = ?,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (
                    finalization.run_status.value,
                    json.dumps(completion_payload, sort_keys=True),
                    json.dumps(finalization.evidence, sort_keys=True),
                    exit_status,
                    finalization.raw_response,
                    json.dumps(finalization.diagnostics, sort_keys=True),
                    agent_run_id,
                    AgentRunStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Agent run {agent_run_id} could not be finalized.")

            blocked_reason = ""
            resumable_status = ""
            if finalization.run_status == AgentRunStatus.FAILED:
                blocked_reason = (
                    finalization.blocked_reason.strip()
                    or finalization.completion.summary
                )
                resumable_status = finalization.resumable_status or entry_status
            elif finalization.run_status == AgentRunStatus.CANCELLED:
                cursor.execute(
                    "SELECT blocked_reason, resumable_status FROM tickets WHERE id = ?",
                    (work_item_id,),
                )
                existing = cursor.fetchone()
                blocked_reason = existing["blocked_reason"] or ""
                resumable_status = existing["resumable_status"] or ""

            cursor.execute(
                """
                UPDATE tickets
                SET status = ?, blocked_reason = ?, resumable_status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (target_status, blocked_reason, resumable_status, work_item_id),
            )
            self._record_status_transition(
                cursor,
                work_item_id,
                current_status,
                target_status,
                reason=(
                    f"Agent run #{agent_run_id} finalized as "
                    f"{finalization.run_status.value}"
                ),
                agent_run_id=agent_run_id,
            )

            if finalization.run_status == AgentRunStatus.SUCCESS:
                self._apply_success_finalization(
                    cursor,
                    work_item_id,
                    agent_run_id,
                    finalization,
                    raw_commit_hashes=run["commit_hashes"],
                )

            if finalization.comment:
                cursor.execute(
                    "INSERT INTO comments (ticket_id, text, author) VALUES (?, ?, 'Ariadne')",
                    (work_item_id, finalization.comment),
                )

            if finalization.handoff_context:
                author = run["agent_name"] or "Ariadne"
                entry = f"[{author}]\n{finalization.handoff_context}"
                existing_context = run["shared_context"] or ""
                new_context = f"{existing_context.rstrip()}\n\n{entry}".strip()
                cursor.execute(
                    "UPDATE tickets SET shared_context = ? WHERE id = ?",
                    (new_context, work_item_id),
                )
                cursor.execute(
                    """
                    INSERT INTO context_entries (
                        ticket_id, author, kind, content, agent_run_id, metadata
                    ) VALUES (?, ?, 'handoff', ?, ?, ?)
                    """,
                    (
                        work_item_id,
                        author,
                        finalization.handoff_context,
                        agent_run_id,
                        json.dumps(finalization.handoff_metadata, sort_keys=True),
                    ),
                )

            conn.commit()

    def _final_status(
        self,
        finalization: AgentRunFinalization,
        *,
        entry_status: str,
        current_status: str,
    ) -> str:
        if finalization.run_status == AgentRunStatus.SUCCESS:
            if not finalization.next_status:
                raise ValueError("Successful finalization requires a next status.")
            return WorkItemStatus(finalization.next_status).value
        if finalization.run_status == AgentRunStatus.FAILED:
            return WorkItemStatus.BLOCKED.value
        if finalization.run_status == AgentRunStatus.CANCELLED:
            return entry_status or current_status
        raise ValueError(
            f"Unsupported terminal run status: {finalization.run_status.value}"
        )

    def _apply_success_finalization(
        self,
        cursor: sqlite3.Cursor,
        work_item_id: str,
        agent_run_id: str,
        finalization: AgentRunFinalization,
        *,
        raw_commit_hashes: str,
    ) -> None:
        commit_hashes = self._parse_commit_hashes(raw_commit_hashes)
        for commit_hash in finalization.commit_hashes:
            normalized = commit_hash.strip()
            if normalized and normalized not in commit_hashes:
                commit_hashes.append(normalized)
        cursor.execute(
            "UPDATE tickets SET commit_hashes = ? WHERE id = ?",
            (json.dumps(commit_hashes), work_item_id),
        )

        for artifact in finalization.completion.artifacts:
            metadata = dict(artifact.metadata)
            if artifact.stable_id:
                metadata["stable_id"] = artifact.stable_id
            cursor.execute(
                """
                SELECT id FROM artifacts
                WHERE ticket_id = ? AND title = ? AND url = ?
                """,
                (work_item_id, artifact.title, artifact.url),
            )
            existing = cursor.fetchone()
            values = (
                artifact.type,
                agent_run_id,
                json.dumps(metadata, sort_keys=True),
            )
            if existing:
                cursor.execute(
                    """
                    UPDATE artifacts
                    SET artifact_type = ?, agent_run_id = ?, metadata = ?
                    WHERE id = ?
                    """,
                    (*values, existing["id"]),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO artifacts (
                        ticket_id, title, url, artifact_type, agent_run_id, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        work_item_id,
                        artifact.title,
                        artifact.url,
                        *values,
                    ),
                )

        gate_decision = finalization.completion.gate_decision
        if gate_decision:
            gate_column = f"gate_{gate_decision.gate.lower()}_status"
            if gate_column not in {
                "gate_analysis_status",
                "gate_design_status",
                "gate_test_status",
            }:
                raise ValueError(f"Invalid gate name: {gate_decision.gate}")
            cursor.execute(
                f"UPDATE tickets SET {gate_column} = ? WHERE id = ?",
                (gate_decision.decision.value, work_item_id),
            )

    def list_agent_runs(self, work_item_id: str) -> List[AgentRun]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM agent_runs WHERE ticket_id = ? ORDER BY started_at ASC, id ASC",
                (work_item_id,),
            )
            rows = cursor.fetchall()
            return [self._agent_run_from_row(row) for row in rows]

    def _agent_run_from_row(self, row: sqlite3.Row) -> AgentRun:
        return AgentRun(
            id=str(row["id"]),
            work_item_id=str(row["ticket_id"]),
            agent_name=row["agent_name"],
            status=AgentRunStatus(row["status"]),
            started_at=row["started_at"] or "",
            finished_at=row["finished_at"] or "",
            task_description=row["task_description"] or "",
            completion_payload=self._parse_json_object(
                row["completion_payload"],
                "completion_payload",
            ),
            evidence=self._parse_json_object(row["evidence"], "evidence"),
            entry_status=row["entry_status"] or "",
            exit_status=row["exit_status"] or "",
            raw_response=row["raw_response"] or "",
            diagnostics=self._parse_json_object(row["diagnostics"], "diagnostics"),
        )

    def add_tool_log(
        self,
        work_item_id: str,
        tool_name: str,
        status: str,
        args: dict,
        result: str = "",
    ) -> None:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT tool_logs FROM tickets WHERE id = ?", (work_item_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Work item {work_item_id} not found.")

            logs = self._parse_json_list(row["tool_logs"], "tool_logs")
            logs.append(
                {
                    "timestamp": self._current_timestamp(cursor),
                    "tool_name": tool_name,
                    "status": status,
                    "args": args,
                    "result": result,
                }
            )
            cursor.execute(
                "UPDATE tickets SET tool_logs = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(logs), work_item_id),
            )
            conn.commit()

    def _current_timestamp(self, cursor: sqlite3.Cursor) -> str:
        cursor.execute("SELECT CURRENT_TIMESTAMP")
        return str(cursor.fetchone()[0])

    def update_git_metadata(
        self,
        work_item_id: str,
        target_branch: str | None = None,
        feature_branch: str | None = None,
        base_commit: str | None = None,
        merge_request_id: str | None = None,
    ) -> None:
        fields = {
            "target_branch": target_branch,
            "feature_branch": feature_branch,
            "base_commit": base_commit,
            "merge_request_id": merge_request_id,
        }
        updates = {
            field_name: field_value.strip()
            for field_name, field_value in fields.items()
            if field_value is not None
        }
        if not updates:
            return

        assignments = ", ".join([f"{field_name} = ?" for field_name in updates])
        values = list(updates.values()) + [work_item_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE tickets SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Work item {work_item_id} not found.")
            conn.commit()

    def get_blockers(self, work_item_id: str) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT relationships.target_ticket_id
                FROM work_item_relationships AS relationships
                JOIN tickets AS target ON target.id = relationships.target_ticket_id
                WHERE relationships.source_ticket_id = ?
                  AND relationships.relationship_type = ?
                  AND target.status <> ?
                UNION
                SELECT relationships.source_ticket_id
                FROM work_item_relationships AS relationships
                JOIN tickets AS source ON source.id = relationships.source_ticket_id
                WHERE relationships.target_ticket_id = ?
                  AND relationships.relationship_type = ?
                  AND source.status <> ?
                ORDER BY 1
                """,
                (
                    work_item_id,
                    WorkItemRelationshipType.DEPENDS_ON.value,
                    WorkItemStatus.DONE.value,
                    work_item_id,
                    WorkItemRelationshipType.BLOCKS.value,
                    WorkItemStatus.DONE.value,
                ),
            )
            return [str(row[0]) for row in cursor.fetchall()]

    def add_work_item_relationship(
        self,
        source_work_item_id: str,
        target_work_item_id: str,
        relationship_type: WorkItemRelationshipType,
    ) -> str:
        if source_work_item_id == target_work_item_id:
            raise ValueError("A work item cannot relate to itself.")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM tickets WHERE id IN (?, ?)",
                (source_work_item_id, target_work_item_id),
            )
            if len(cursor.fetchall()) != 2:
                raise ValueError(
                    "Both work items must exist before adding a relationship."
                )
            cursor.execute(
                """
                INSERT INTO work_item_relationships (
                    source_ticket_id, target_ticket_id, relationship_type
                ) VALUES (?, ?, ?)
                ON CONFLICT(source_ticket_id, target_ticket_id, relationship_type)
                DO NOTHING
                """,
                (
                    source_work_item_id,
                    target_work_item_id,
                    relationship_type.value,
                ),
            )
            cursor.execute(
                """
                SELECT id FROM work_item_relationships
                WHERE source_ticket_id = ? AND target_ticket_id = ?
                  AND relationship_type = ?
                """,
                (
                    source_work_item_id,
                    target_work_item_id,
                    relationship_type.value,
                ),
            )
            relationship_id = cursor.fetchone()[0]
            conn.commit()
            return str(relationship_id)

    def list_work_item_relationships(
        self,
        work_item_id: str,
    ) -> List[WorkItemRelationship]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM work_item_relationships
                WHERE source_ticket_id = ? OR target_ticket_id = ?
                ORDER BY id ASC
                """,
                (work_item_id, work_item_id),
            )
            return [
                WorkItemRelationship(
                    id=str(row["id"]),
                    source_work_item_id=str(row["source_ticket_id"]),
                    target_work_item_id=str(row["target_ticket_id"]),
                    relationship_type=WorkItemRelationshipType(
                        row["relationship_type"]
                    ),
                    created_at=row["created_at"] or "",
                )
                for row in cursor.fetchall()
            ]

    def list_status_history(self, work_item_id: str) -> List[WorkItemStatusHistory]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM work_item_status_history
                WHERE ticket_id = ? ORDER BY id ASC
                """,
                (work_item_id,),
            )
            return [
                WorkItemStatusHistory(
                    id=str(row["id"]),
                    work_item_id=str(row["ticket_id"]),
                    from_status=row["from_status"] or "",
                    to_status=row["to_status"],
                    reason=row["reason"] or "",
                    agent_run_id=str(row["agent_run_id"] or ""),
                    created_at=row["created_at"] or "",
                )
                for row in cursor.fetchall()
            ]

    def list_work_items(self) -> List[WorkItem]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM tickets ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [self.get_work_item(str(r["id"])) for r in rows]


# Backwards-compatible name while callers are migrated.
SQLiteTicketSystem = SQLiteWorkItemStore
