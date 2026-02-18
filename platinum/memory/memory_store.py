"""Persistent Memory System — Platinum tier.

Provides structured memory backed by SQLite with:
- Task history search
- Context recall
- Semantic tagging
- Conversation memory
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("platinum.memory")


class MemoryStore:
    """Persistent memory backed by SQLite.

    Stores task history, context, decisions, and learned patterns
    for recall across sessions.
    """

    def __init__(self, db_path: str = "platinum.db") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        """Create memory tables."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                importance INTEGER NOT NULL DEFAULT 5,
                created TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                verdict TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL,
                completed TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS context_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding_key TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                created TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL DEFAULT '',
                decision TEXT NOT NULL,
                reasoning TEXT NOT NULL DEFAULT '',
                outcome TEXT NOT NULL DEFAULT '',
                created TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
            CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories(tags);
            CREATE INDEX IF NOT EXISTS idx_task_history_task_id ON task_history(task_id);
            CREATE INDEX IF NOT EXISTS idx_task_history_status ON task_history(status);
            CREATE INDEX IF NOT EXISTS idx_context_tags ON context_entries(tags);
        """)
        self._conn.commit()

    # ── Memory CRUD ──────────────────────────────────────────────────

    def store(self, category: str, key: str, value: str,
             tags: list[str] | None = None, importance: int = 5) -> int:
        """Store a memory entry."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = self._conn.execute(
            """INSERT INTO memories (category, key, value, tags, importance, created, last_accessed)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (category, key, value, ",".join(tags or []), importance, now, now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def recall(self, category: str | None = None, key: str | None = None,
              tags: list[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Recall memories by category, key, or tags."""
        query = "SELECT * FROM memories WHERE 1=1"
        params: list[Any] = []

        if category:
            query += " AND category = ?"
            params.append(category)
        if key:
            query += " AND key LIKE ?"
            params.append(f"%{key}%")
        if tags:
            for tag in tags:
                query += " AND tags LIKE ?"
                params.append(f"%{tag}%")

        query += " ORDER BY importance DESC, last_accessed DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()

        # Update access count
        for row in rows:
            self._conn.execute(
                "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), row["id"]),
            )
        self._conn.commit()

        return [dict(row) for row in rows]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Full-text search across all memories."""
        rows = self._conn.execute(
            """SELECT * FROM memories
               WHERE key LIKE ? OR value LIKE ? OR tags LIKE ?
               ORDER BY importance DESC, last_accessed DESC
               LIMIT ?""",
            (f"%{query}%", f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def forget(self, memory_id: int) -> bool:
        """Delete a memory entry."""
        cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    # ── Task History ─────────────────────────────────────────────────

    def record_task(self, task_id: str, title: str, status: str,
                   plan: str = "", result: str = "", verdict: str = "",
                   duration_ms: int = 0) -> int:
        """Record a task in history."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        completed = now if status in ("completed", "failed") else ""
        cursor = self._conn.execute(
            """INSERT INTO task_history (task_id, title, status, plan, result, verdict,
                                       duration_ms, created, completed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, title, status, plan, result, verdict, duration_ms, now, completed),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_task_history(self, task_id: str | None = None,
                        status: str | None = None,
                        limit: int = 50) -> list[dict[str, Any]]:
        """Get task history, optionally filtered."""
        query = "SELECT * FROM task_history WHERE 1=1"
        params: list[Any] = []

        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def search_task_history(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search task history by title or content."""
        rows = self._conn.execute(
            """SELECT * FROM task_history
               WHERE title LIKE ? OR plan LIKE ? OR result LIKE ?
               ORDER BY created DESC LIMIT ?""",
            (f"%{query}%", f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        return [dict(row) for row in rows]

    # ── Context Entries ──────────────────────────────────────────────

    def store_context(self, source: str, content: str,
                     tags: list[str] | None = None) -> int:
        """Store a context entry for later recall."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = self._conn.execute(
            """INSERT INTO context_entries (source, content, tags, created)
               VALUES (?, ?, ?, ?)""",
            (source, content, ",".join(tags or []), now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def recall_context(self, tags: list[str] | None = None,
                      source: str | None = None,
                      limit: int = 10) -> list[dict[str, Any]]:
        """Recall context entries."""
        query = "SELECT * FROM context_entries WHERE 1=1"
        params: list[Any] = []

        if source:
            query += " AND source = ?"
            params.append(source)
        if tags:
            for tag in tags:
                query += " AND tags LIKE ?"
                params.append(f"%{tag}%")

        query += " ORDER BY created DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    # ── Decisions ────────────────────────────────────────────────────

    def record_decision(self, decision: str, reasoning: str = "",
                       outcome: str = "", task_id: str = "") -> int:
        """Record a decision for future reference."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = self._conn.execute(
            """INSERT INTO decisions (task_id, decision, reasoning, outcome, created)
               VALUES (?, ?, ?, ?, ?)""",
            (task_id, decision, reasoning, outcome, now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_decisions(self, task_id: str | None = None,
                     limit: int = 20) -> list[dict[str, Any]]:
        """Get recorded decisions."""
        if task_id:
            rows = self._conn.execute(
                "SELECT * FROM decisions WHERE task_id = ? ORDER BY created DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM decisions ORDER BY created DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get memory store statistics."""
        memory_count = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        task_count = self._conn.execute("SELECT COUNT(*) FROM task_history").fetchone()[0]
        context_count = self._conn.execute("SELECT COUNT(*) FROM context_entries").fetchone()[0]
        decision_count = self._conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]

        return {
            "memories": memory_count,
            "task_history": task_count,
            "context_entries": context_count,
            "decisions": decision_count,
        }

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
