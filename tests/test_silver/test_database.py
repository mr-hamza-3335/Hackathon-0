"""Tests for the SQLite memory layer (memory/database.py)."""

import pytest
from pathlib import Path

from memory.database import TaskDatabase


@pytest.fixture
def db(tmp_path):
    """Create a temporary database for testing."""
    database = TaskDatabase(db_path=tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def sample_task():
    return {
        "id": "task-test-001",
        "status": "pending",
        "priority": "high",
        "source": "test",
        "title": "Test Task",
        "body": "This is a test task body.",
        "tags": ["test", "demo"],
        "approval_required": True,
        "file_path": "/tmp/test-task.md",
        "created": "2026-01-01T00:00:00",
    }


@pytest.fixture
def vault_with_tasks(tmp_path):
    """Create a temporary vault with task files."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    archive_dir = tasks_dir / "archive"
    archive_dir.mkdir()

    # Active task
    active = tasks_dir / "2026-01-01_active-task.md"
    active.write_text(
        "---\nid: task-active-001\nstatus: pending\npriority: high\n---\n\n## Request\n\nActive task.\n",
        encoding="utf-8",
    )

    # Archived task
    archived = archive_dir / "2026-01-01_archived-task.md"
    archived.write_text(
        "---\nid: task-archived-001\nstatus: completed\npriority: low\n---\n\n## Request\n\nArchived task.\n",
        encoding="utf-8",
    )

    # Template file (should be ignored)
    template = tasks_dir / "_template.md"
    template.write_text("---\nid: template\nstatus: new\n---\n\nTemplate.\n", encoding="utf-8")

    return tasks_dir


class TestUpsertAndGet:
    def test_upsert_creates_task(self, db, sample_task):
        db.upsert_task(sample_task)
        result = db.get_task("task-test-001")
        assert result is not None
        assert result["id"] == "task-test-001"
        assert result["status"] == "pending"
        assert result["priority"] == "high"
        assert result["title"] == "Test Task"

    def test_upsert_updates_existing(self, db, sample_task):
        db.upsert_task(sample_task)
        sample_task["status"] = "planning"
        sample_task["priority"] = "low"
        db.upsert_task(sample_task)
        result = db.get_task("task-test-001")
        assert result["status"] == "planning"
        assert result["priority"] == "low"

    def test_get_nonexistent_returns_none(self, db):
        assert db.get_task("nonexistent") is None

    def test_tags_stored_as_list(self, db, sample_task):
        db.upsert_task(sample_task)
        result = db.get_task("task-test-001")
        assert result["tags"] == ["test", "demo"]

    def test_approval_required_as_bool(self, db, sample_task):
        db.upsert_task(sample_task)
        result = db.get_task("task-test-001")
        assert result["approval_required"] is True


class TestGetAllTasks:
    def test_returns_all_tasks(self, db, sample_task):
        db.upsert_task(sample_task)
        task2 = sample_task.copy()
        task2["id"] = "task-test-002"
        task2["status"] = "completed"
        db.upsert_task(task2)
        all_tasks = db.get_all_tasks()
        assert len(all_tasks) == 2

    def test_filter_by_status(self, db, sample_task):
        db.upsert_task(sample_task)
        task2 = sample_task.copy()
        task2["id"] = "task-test-002"
        task2["status"] = "completed"
        db.upsert_task(task2)

        pending = db.get_all_tasks(status="pending")
        assert len(pending) == 1
        assert pending[0]["id"] == "task-test-001"

        completed = db.get_all_tasks(status="completed")
        assert len(completed) == 1
        assert completed[0]["id"] == "task-test-002"

    def test_filter_returns_empty_for_no_match(self, db, sample_task):
        db.upsert_task(sample_task)
        result = db.get_all_tasks(status="nonexistent")
        assert len(result) == 0


class TestUpdateStatus:
    def test_update_status(self, db, sample_task):
        db.upsert_task(sample_task)
        db.update_task_status("task-test-001", "planning")
        result = db.get_task("task-test-001")
        assert result["status"] == "planning"


class TestTransitions:
    def test_record_and_get_transitions(self, db, sample_task):
        db.upsert_task(sample_task)
        db.record_transition("task-test-001", "pending", "planning")
        db.record_transition("task-test-001", "planning", "awaiting-approval")

        transitions = db.get_transitions("task-test-001")
        assert len(transitions) == 2
        assert transitions[0]["old_status"] == "pending"
        assert transitions[0]["new_status"] == "planning"
        assert transitions[1]["old_status"] == "planning"
        assert transitions[1]["new_status"] == "awaiting-approval"


class TestExecutionHistory:
    def test_record_and_get_history(self, db, sample_task):
        db.upsert_task(sample_task)
        db.record_execution_step(
            task_id="task-test-001",
            step_number=1,
            action="execute-draft_email",
            tool="draft_email",
            status="success",
            duration_ms=150,
        )
        history = db.get_execution_history("task-test-001")
        assert len(history) == 1
        assert history[0]["tool"] == "draft_email"
        assert history[0]["duration_ms"] == 150


class TestVaultSync:
    def test_sync_from_vault(self, db, vault_with_tasks):
        count = db.sync_from_vault(vault_with_tasks)
        assert count == 2  # active + archived, not template

        active = db.get_task("task-active-001")
        assert active is not None
        assert active["status"] == "pending"

        archived = db.get_task("task-archived-001")
        assert archived is not None
        assert archived["status"] == "completed"

    def test_sync_single_task(self, db, vault_with_tasks):
        task_file = vault_with_tasks / "2026-01-01_active-task.md"
        result = db.sync_single_task(task_file)
        assert result is not None
        assert result["id"] == "task-active-001"

    def test_sync_detects_status_change(self, db, vault_with_tasks):
        task_file = vault_with_tasks / "2026-01-01_active-task.md"
        db.sync_single_task(task_file)

        # Manually change the file
        task_file.write_text(
            "---\nid: task-active-001\nstatus: planning\npriority: high\n---\n\n## Request\n\nUpdated.\n",
            encoding="utf-8",
        )
        db.sync_single_task(task_file)

        result = db.get_task("task-active-001")
        assert result["status"] == "planning"

        transitions = db.get_transitions("task-active-001")
        assert len(transitions) == 1
        assert transitions[0]["old_status"] == "pending"
        assert transitions[0]["new_status"] == "planning"

    def test_sync_ignores_no_frontmatter(self, db, tmp_path):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        bad_file = tasks_dir / "no-frontmatter.md"
        bad_file.write_text("Just plain text, no YAML.", encoding="utf-8")

        result = db.sync_single_task(bad_file)
        assert result is None


class TestDeleteTask:
    def test_delete_removes_all_records(self, db, sample_task):
        db.upsert_task(sample_task)
        db.record_transition("task-test-001", "pending", "planning")
        db.record_execution_step(task_id="task-test-001", step_number=1, status="success")

        db.delete_task("task-test-001")

        assert db.get_task("task-test-001") is None
        assert len(db.get_transitions("task-test-001")) == 0
        assert len(db.get_execution_history("task-test-001")) == 0
