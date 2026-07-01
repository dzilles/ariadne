import sqlite3
import logging
import json
from typing import List

from src.ariadne.work_items.models import (
    ArtifactLink,
    Comment,
    GateStatus,
    ToolLogEntry,
    WorkItem,
    WorkItemStatus,
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
            cursor.execute('''
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
                    merge_request_id TEXT DEFAULT ''
                )
            ''')
            self._ensure_ticket_column(cursor, "updated_at", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "commit_hashes", "TEXT DEFAULT '[]'")
            self._ensure_ticket_column(cursor, "tool_logs", "TEXT DEFAULT '[]'")
            self._ensure_ticket_column(cursor, "shared_context", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "target_branch", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "feature_branch", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "base_commit", "TEXT DEFAULT ''")
            self._ensure_ticket_column(cursor, "merge_request_id", "TEXT DEFAULT ''")
            cursor.execute(
                """
                UPDATE tickets
                SET updated_at = COALESCE(NULLIF(created_at, ''), CURRENT_TIMESTAMP)
                WHERE updated_at IS NULL OR updated_at = ''
                """
            )
            
            # Comments Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    author TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticket_id) REFERENCES tickets (id)
                )
            ''')
            
            # Artifacts Table (Links)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticket_id) REFERENCES tickets (id)
                )
            ''')
            
            # Assignees Table (Many-to-Many or simple list for now)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS assignees (
                    ticket_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    FOREIGN KEY (ticket_id) REFERENCES tickets (id)
                )
            ''')
            
            conn.commit()

    def _ensure_ticket_column(self, cursor: sqlite3.Cursor, column_name: str, definition: str) -> None:
        cursor.execute("PRAGMA table_info(tickets)")
        columns = {row[1] for row in cursor.fetchall()}
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE tickets ADD COLUMN {column_name} {definition}")

    def _touch_work_item(self, cursor: sqlite3.Cursor, work_item_id: str) -> None:
        cursor.execute("UPDATE tickets SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (work_item_id,))

    def _parse_json_list(self, raw_json: str | None, field_name: str) -> list:
        if not raw_json:
            return []
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("Invalid %s JSON in work item row; returning empty list.", field_name)
            return []
        if not isinstance(parsed, list):
            return []

        return parsed

    def _parse_commit_hashes(self, raw_hashes: str | None) -> List[str]:
        return [str(commit_hash) for commit_hash in self._parse_json_list(raw_hashes, "commit_hashes")]

    def _parse_tool_logs(self, raw_logs: str | None) -> List[ToolLogEntry]:
        entries = []
        for raw_entry in self._parse_json_list(raw_logs, "tool_logs"):
            if not isinstance(raw_entry, dict):
                continue
            try:
                entries.append(ToolLogEntry(**raw_entry))
            except Exception:
                logger.warning("Invalid tool log entry in work item row; skipping entry.")
        return entries

    def create_work_item(self, title: str, description: str, type: WorkItemType, priority: str) -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tickets (title, description, status, type, priority) VALUES (?, ?, ?, ?, ?)",
                (title, description, WorkItemStatus.BACKLOG.value, type.value, priority)
            )
            ticket_id = cursor.lastrowid
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
            cursor.execute("SELECT * FROM comments WHERE ticket_id = ? ORDER BY created_at ASC", (work_item_id,))
            comment_rows = cursor.fetchall()
            comments = [
                Comment(
                    id=str(r['id']),
                    text=r['text'],
                    author=r['author'],
                    created_at=r['created_at']
                ) for r in comment_rows
            ]

            # Fetch Artifacts
            cursor.execute("SELECT * FROM artifacts WHERE ticket_id = ?", (work_item_id,))
            artifact_rows = cursor.fetchall()
            artifacts = [
                ArtifactLink(title=r['title'], url=r['url']) for r in artifact_rows
            ]

            # Fetch Assignees
            cursor.execute("SELECT name FROM assignees WHERE ticket_id = ?", (work_item_id,))
            assignee_rows = cursor.fetchall()
            assignees = [r['name'] for r in assignee_rows]

            return WorkItem(
                id=str(row['id']),
                title=row['title'],
                description=row['description'] or "",
                status=row['status'],
                type=WorkItemType(row['type']),
                assignees=assignees,
                comments=comments,
                artifacts=artifacts,
                created_at=row['created_at'] or "",
                updated_at=row['updated_at'] or "",
                commit_hashes=self._parse_commit_hashes(row['commit_hashes']),
                tool_logs=self._parse_tool_logs(row['tool_logs']),
                shared_context=row['shared_context'] or "",
                target_branch=row['target_branch'] or "",
                feature_branch=row['feature_branch'] or "",
                base_commit=row['base_commit'] or "",
                merge_request_id=row['merge_request_id'] or "",
                gate_analysis_status=GateStatus(row['gate_analysis_status']),
                gate_design_status=GateStatus(row['gate_design_status']),
                gate_test_status=GateStatus(row['gate_test_status'])
            )

    def search_work_items(self, query: str) -> List[WorkItem]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM tickets WHERE title LIKE ? OR description LIKE ?",
                (f"%{query}%", f"%{query}%")
            )
            rows = cursor.fetchall()
            return [self.get_work_item(str(r['id'])) for r in rows]

    def update_status(self, work_item_id: str, status: WorkItemStatus) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tickets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status.value, work_item_id)
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Work item {work_item_id} not found.")
            conn.commit()

    def update_description(self, work_item_id: str, description: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tickets SET description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (description, work_item_id)
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
                (work_item_id, text, author)
            )
            self._touch_work_item(cursor, work_item_id)
            conn.commit()

    def set_gate_status(self, work_item_id: str, gate: str, status: GateStatus) -> None:
        gate_col = f"gate_{gate.lower()}_status"
        # Validate column to prevent injection (though gate is controlled by Enum/Internal logic)
        if gate_col not in ['gate_analysis_status', 'gate_design_status', 'gate_test_status']:
            raise ValueError(f"Invalid gate name: {gate}")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE tickets SET {gate_col} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status.value, work_item_id)
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Work item {work_item_id} not found.")
            conn.commit()

    def add_artifact_link(self, work_item_id: str, title: str, url: str, comment: str = None) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO artifacts (ticket_id, title, url) VALUES (?, ?, ?)",
                (work_item_id, title, url)
            )
            self._touch_work_item(cursor, work_item_id)
            conn.commit()
            if comment:
                self.post_comment(work_item_id, comment)

    def add_commit_hash(self, work_item_id: str, commit_hash: str) -> None:
        commit_hash = commit_hash.strip()
        if not commit_hash:
            raise ValueError("Commit hash cannot be empty.")

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT commit_hashes FROM tickets WHERE id = ?", (work_item_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Work item {work_item_id} not found.")

            hashes = self._parse_commit_hashes(row["commit_hashes"])
            if commit_hash not in hashes:
                hashes.append(commit_hash)
                cursor.execute(
                    "UPDATE tickets SET commit_hashes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(hashes), work_item_id)
                )
            conn.commit()

    def append_shared_context(self, work_item_id: str, author: str, context: str) -> None:
        context = context.strip()
        if not context:
            raise ValueError("Shared context cannot be empty.")

        entry = f"[{author.strip() or 'Ariadne'}]\n{context}"
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT shared_context FROM tickets WHERE id = ?", (work_item_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Work item {work_item_id} not found.")

            existing_context = row["shared_context"] or ""
            new_context = f"{existing_context.rstrip()}\n\n{entry}".strip()
            cursor.execute(
                "UPDATE tickets SET shared_context = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_context, work_item_id)
            )
            conn.commit()

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
            cursor.execute("SELECT tool_logs FROM tickets WHERE id = ?", (work_item_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Work item {work_item_id} not found.")

            logs = self._parse_json_list(row["tool_logs"], "tool_logs")
            logs.append({
                "timestamp": self._current_timestamp(cursor),
                "tool_name": tool_name,
                "status": status,
                "args": args,
                "result": result,
            })
            cursor.execute(
                "UPDATE tickets SET tool_logs = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(logs), work_item_id)
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
                values
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Work item {work_item_id} not found.")
            conn.commit()

    def get_blockers(self, work_item_id: str) -> List[str]:
        # TODO: Implement work item relations in SQLite if needed.
        return []

    def list_work_items(self) -> List[WorkItem]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM tickets ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [self.get_work_item(str(r['id'])) for r in rows]


# Backwards-compatible name while callers are migrated.
SQLiteTicketSystem = SQLiteWorkItemStore
