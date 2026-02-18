"""SQLite persistence layer — read-optimized index of vault task files.

The vault remains source of truth. This database provides fast querying,
status transition history, and execution step tracking for the web UI.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from watchers.utils.markdown_parser import parse_frontmatter


DB_PATH = Path(__file__).parent.parent / "silver.db"


class TaskDatabase:
    """SQLite-backed task store that syncs from vault markdown files."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                priority TEXT NOT NULL DEFAULT 'medium',
                source TEXT NOT NULL DEFAULT 'unknown',
                title TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                approval_required INTEGER NOT NULL DEFAULT 1,
                file_path TEXT NOT NULL DEFAULT '',
                created TEXT NOT NULL DEFAULT '',
                last_updated TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS status_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                old_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS execution_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                step_number INTEGER NOT NULL DEFAULT 0,
                action TEXT NOT NULL DEFAULT '',
                tool TEXT NOT NULL DEFAULT '',
                input_summary TEXT NOT NULL DEFAULT '',
                output_summary TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );
        """)
        self.conn.commit()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def upsert_task(self, task_data: dict[str, Any]) -> None:
        """Insert or update a task record."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        tags = task_data.get("tags", [])
        if isinstance(tags, list):
            tags = ",".join(tags)

        self.conn.execute("""
            INSERT INTO tasks (id, status, priority, source, title, body,
                               tags, approval_required, file_path, created, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                priority=excluded.priority,
                source=excluded.source,
                title=excluded.title,
                body=excluded.body,
                tags=excluded.tags,
                approval_required=excluded.approval_required,
                file_path=excluded.file_path,
                last_updated=excluded.last_updated
        """, (
            task_data.get("id", ""),
            task_data.get("status", "pending"),
            task_data.get("priority", "medium"),
            task_data.get("source", "unknown"),
            task_data.get("title", ""),
            task_data.get("body", ""),
            tags,
            1 if task_data.get("approval_required", True) else 0,
            str(task_data.get("file_path", "")),
            task_data.get("created", now),
            now,
        ))
        self.conn.commit()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get a single task by ID."""
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def get_all_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        """Get all tasks, optionally filtered by status."""
        if status:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY last_updated DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks ORDER BY last_updated DESC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_task_status(self, task_id: str, new_status: str) -> None:
        """Update just the status field of a task."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE tasks SET status = ?, last_updated = ? WHERE id = ?",
            (new_status, now, task_id),
        )
        self.conn.commit()

    def delete_task(self, task_id: str) -> None:
        """Delete a task and its related records."""
        self.conn.execute("DELETE FROM execution_history WHERE task_id = ?", (task_id,))
        self.conn.execute("DELETE FROM status_transitions WHERE task_id = ?", (task_id,))
        self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def record_transition(
        self, task_id: str, old_status: str, new_status: str
    ) -> None:
        """Record a status transition for audit trail."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT INTO status_transitions (task_id, old_status, new_status, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (task_id, old_status, new_status, now),
        )
        self.conn.commit()

    def get_transitions(self, task_id: str) -> list[dict[str, Any]]:
        """Get all status transitions for a task."""
        rows = self.conn.execute(
            "SELECT * FROM status_transitions WHERE task_id = ? ORDER BY timestamp",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Execution history
    # ------------------------------------------------------------------

    def record_execution_step(
        self,
        task_id: str,
        step_number: int = 0,
        action: str = "",
        tool: str = "",
        input_summary: str = "",
        output_summary: str = "",
        status: str = "",
        error: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Record an execution step."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.conn.execute("""
            INSERT INTO execution_history
                (task_id, step_number, action, tool, input_summary,
                 output_summary, status, error, duration_ms, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id, step_number, action, tool, input_summary,
            output_summary, status, error, duration_ms, now,
        ))
        self.conn.commit()

    def get_execution_history(self, task_id: str) -> list[dict[str, Any]]:
        """Get execution history for a task."""
        rows = self.conn.execute(
            "SELECT * FROM execution_history WHERE task_id = ? ORDER BY step_number",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Vault sync
    # ------------------------------------------------------------------

    def sync_from_vault(self, vault_tasks_dir: Path) -> int:
        """Sync all task files from vault into the database.

        Scans vault/tasks/ and vault/tasks/archive/ for .md files.
        Returns the number of tasks synced.
        """
        count = 0
        dirs_to_scan = [vault_tasks_dir]
        archive_dir = vault_tasks_dir / "archive"
        if archive_dir.exists():
            dirs_to_scan.append(archive_dir)

        for scan_dir in dirs_to_scan:
            for md_file in scan_dir.glob("*.md"):
                if md_file.name.startswith("_"):
                    continue
                try:
                    self.sync_single_task(md_file)
                    count += 1
                except Exception:
                    pass

        return count

    def sync_single_task(self, file_path: Path) -> dict[str, Any] | None:
        """Sync a single vault task file into the database.

        Returns the task data dict, or None if the file has no valid frontmatter.
        """
        fm, body = parse_frontmatter(file_path)
        if not fm.get("id"):
            return None

        # Derive title from filename
        stem = file_path.stem
        if len(stem) > 11 and stem[10] == "_":
            stem = stem[11:]
        title = stem.replace("-", " ").replace("_", " ").title()

        old = self.get_task(fm["id"])
        old_status = old["status"] if old else None

        task_data = {
            "id": fm["id"],
            "status": fm.get("status", "pending"),
            "priority": fm.get("priority", "medium"),
            "source": fm.get("source", "unknown"),
            "title": title,
            "body": body,
            "tags": fm.get("tags", []),
            "approval_required": fm.get("approval_required", True),
            "file_path": str(file_path),
            "created": fm.get("created", ""),
        }
        self.upsert_task(task_data)

        # Record transition if status changed
        new_status = task_data["status"]
        if old_status and old_status != new_status:
            self.record_transition(fm["id"], old_status, new_status)

        return task_data

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        if "tags" in d and isinstance(d["tags"], str):
            d["tags"] = [t for t in d["tags"].split(",") if t]
        if "approval_required" in d:
            d["approval_required"] = bool(d["approval_required"])
        return d

    def close(self) -> None:
        self.conn.close()
