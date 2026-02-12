"""Tests for task_manager."""

import pytest
from pathlib import Path
from unittest.mock import patch

from orchestrator.task_manager import TaskManager, TaskStatus, Task, TRANSITIONS
from watchers.utils.markdown_parser import parse_frontmatter, update_frontmatter


@pytest.fixture
def task_mgr(tmp_vault, monkeypatch):
    """Create a TaskManager pointed at the tmp vault."""
    monkeypatch.setattr("orchestrator.task_manager.config.vault.tasks", tmp_vault / "tasks")
    monkeypatch.setattr("orchestrator.task_manager.config.vault.archive", tmp_vault / "tasks" / "archive")
    return TaskManager()


class TestLoadTask:
    def test_load_valid(self, task_mgr, sample_task_file):
        task = task_mgr.load_task(sample_task_file)
        assert task.id == "task-test-001"
        assert task.status == TaskStatus.PENDING
        assert task.priority == "high"
        assert task.approval_required is True
        assert "test" in task.tags

    def test_load_title(self, task_mgr, sample_task_file):
        task = task_mgr.load_task(sample_task_file)
        assert "Test Task" in task.title

    def test_load_body(self, task_mgr, sample_task_file):
        task = task_mgr.load_task(sample_task_file)
        assert "## Request" in task.body


class TestTransitions:
    def test_valid_transition_pending_to_planning(self, task_mgr, sample_task_file):
        task = task_mgr.load_task(sample_task_file)
        task_mgr.transition(task, TaskStatus.PLANNING)
        assert task.status == TaskStatus.PLANNING
        fm, _ = parse_frontmatter(sample_task_file)
        assert fm["status"] == "planning"

    def test_invalid_transition_pending_to_approved(self, task_mgr, sample_task_file):
        task = task_mgr.load_task(sample_task_file)
        with pytest.raises(ValueError, match="Invalid transition"):
            task_mgr.transition(task, TaskStatus.APPROVED)

    def test_invalid_transition_pending_to_completed(self, task_mgr, sample_task_file):
        task = task_mgr.load_task(sample_task_file)
        with pytest.raises(ValueError):
            task_mgr.transition(task, TaskStatus.COMPLETED)

    def test_full_happy_path(self, task_mgr, sample_task_file):
        task = task_mgr.load_task(sample_task_file)
        task_mgr.transition(task, TaskStatus.PLANNING)
        task_mgr.transition(task, TaskStatus.AWAITING_APPROVAL)
        # Simulate human approval by writing directly
        update_frontmatter(sample_task_file, {"status": "approved"})
        task.status = TaskStatus.APPROVED
        task_mgr.transition(task, TaskStatus.EXECUTING)
        task_mgr.transition(task, TaskStatus.COMPLETED)
        assert task.status == TaskStatus.COMPLETED

    def test_all_states_have_transitions(self):
        for status in TaskStatus:
            assert status in TRANSITIONS, f"Missing transitions for {status}"


class TestWritePlan:
    def test_write_plan(self, task_mgr, sample_task_file):
        task = task_mgr.load_task(sample_task_file)
        task_mgr.write_plan(task, "## Proposed Plan\n\n- [ ] Step 1: Test")
        fm, body = parse_frontmatter(sample_task_file)
        assert "## Proposed Plan" in body
        assert "Step 1: Test" in body

    def test_write_plan_preserves_request(self, task_mgr, sample_task_file):
        task = task_mgr.load_task(sample_task_file)
        task_mgr.write_plan(task, "## Proposed Plan\n\n- [ ] Step 1")
        _, body = parse_frontmatter(sample_task_file)
        assert "## Request" in body


class TestWriteResult:
    def test_write_result(self, task_mgr, sample_task_file):
        task = task_mgr.load_task(sample_task_file)
        task_mgr.write_result(task, "All steps passed.")
        _, body = parse_frontmatter(sample_task_file)
        assert "## Execution Result" in body
        assert "All steps passed" in body


class TestArchive:
    def test_archive_task(self, task_mgr, sample_task_file):
        task = task_mgr.load_task(sample_task_file)
        archived = task_mgr.archive_task(task)
        assert archived.exists()
        assert "archive" in str(archived)
        assert not sample_task_file.exists()


class TestTrigger:
    def test_check_trigger_exists(self, task_mgr, tmp_vault):
        trigger = tmp_vault / "tasks" / ".trigger"
        trigger.write_text("task-001", encoding="utf-8")
        result = task_mgr.check_trigger()
        assert result == "task-001"
        assert not trigger.exists()  # consumed

    def test_check_trigger_none(self, task_mgr):
        result = task_mgr.check_trigger()
        assert result is None


class TestGetPendingTasks:
    def test_finds_pending(self, task_mgr, sample_task_file):
        tasks = task_mgr.get_pending_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "task-test-001"

    def test_ignores_non_pending(self, task_mgr, sample_task_file):
        update_frontmatter(sample_task_file, {"status": "completed"})
        tasks = task_mgr.get_pending_tasks()
        assert len(tasks) == 0

    def test_ignores_template_files(self, task_mgr, tmp_vault):
        template = tmp_vault / "tasks" / "_template.md"
        template.write_text("---\nid: tmpl\nstatus: pending\n---\n", encoding="utf-8")
        tasks = task_mgr.get_pending_tasks()
        assert len(tasks) == 0
