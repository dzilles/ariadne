import sqlite3
import logging
from typing import List

from src.ariadne.work_items.models import (
    ArtifactLink,
    Comment,
    GateStatus,
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
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

    def create_ticket(self, title: str, description: str, type: WorkItemType, priority: str) -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tickets (title, description, status, type, priority) VALUES (?, ?, ?, ?, ?)",
                (title, description, WorkItemStatus.BACKLOG.value, type.value, priority)
            )
            ticket_id = cursor.lastrowid
            conn.commit()
            return str(ticket_id)

    def get_ticket(self, ticket_id: str) -> WorkItem:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Fetch work item.
            cursor.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Work item {ticket_id} not found.")

            # Fetch Comments
            cursor.execute("SELECT * FROM comments WHERE ticket_id = ? ORDER BY created_at ASC", (ticket_id,))
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
            cursor.execute("SELECT * FROM artifacts WHERE ticket_id = ?", (ticket_id,))
            artifact_rows = cursor.fetchall()
            artifacts = [
                ArtifactLink(title=r['title'], url=r['url']) for r in artifact_rows
            ]

            # Fetch Assignees
            cursor.execute("SELECT name FROM assignees WHERE ticket_id = ?", (ticket_id,))
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
                gate_analysis_status=GateStatus(row['gate_analysis_status']),
                gate_design_status=GateStatus(row['gate_design_status']),
                gate_test_status=GateStatus(row['gate_test_status'])
            )

    def search_tickets(self, query: str) -> List[WorkItem]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM tickets WHERE title LIKE ? OR description LIKE ?",
                (f"%{query}%", f"%{query}%")
            )
            rows = cursor.fetchall()
            return [self.get_ticket(str(r['id'])) for r in rows]

    def update_status(self, ticket_id: str, status: WorkItemStatus) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tickets SET status = ? WHERE id = ?",
                (status.value, ticket_id)
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Work item {ticket_id} not found.")
            conn.commit()

    def update_description(self, ticket_id: str, description: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tickets SET description = ? WHERE id = ?",
                (description, ticket_id)
            )
            conn.commit()

    def post_comment(self, ticket_id: str, text: str) -> None:
        # For local DB, we can use 'System' or current user as author
        author = "Ariadne" 
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO comments (ticket_id, text, author) VALUES (?, ?, ?)",
                (ticket_id, text, author)
            )
            conn.commit()

    def set_gate_status(self, ticket_id: str, gate: str, status: GateStatus) -> None:
        gate_col = f"gate_{gate.lower()}_status"
        # Validate column to prevent injection (though gate is controlled by Enum/Internal logic)
        if gate_col not in ['gate_analysis_status', 'gate_design_status', 'gate_test_status']:
            raise ValueError(f"Invalid gate name: {gate}")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE tickets SET {gate_col} = ? WHERE id = ?",
                (status.value, ticket_id)
            )
            conn.commit()

    def add_artifact_link(self, ticket_id: str, title: str, url: str, comment: str = None) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO artifacts (ticket_id, title, url) VALUES (?, ?, ?)",
                (ticket_id, title, url)
            )
            conn.commit()
            if comment:
                self.post_comment(ticket_id, comment)

    def get_blockers(self, ticket_id: str) -> List[str]:
        # TODO: Implement work item relations in SQLite if needed.
        return []

    def list_tickets(self) -> List[WorkItem]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM tickets ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [self.get_ticket(str(r['id'])) for r in rows]


# Backwards-compatible name while callers are migrated.
SQLiteTicketSystem = SQLiteWorkItemStore
