"""Tests for approval_gate."""

import pytest
import threading
import time
from pathlib import Path
from unittest.mock import patch

from orchestrator.approval_gate import ApprovalGate, ApprovalTimeout, SystemHalted
from orchestrator.task_manager import Task, TaskStatus
from watchers.utils.markdown_parser import update_frontmatter


def _make_task(file_path: Path) -> Task:
    """Create a minimal Task object for testing."""
    return Task(
        id="task-test-001",
        status=TaskStatus.AWAITING_APPROVAL,
        priority="high",
        source="manual",
        tags=["test"],
        approval_required=True,
        body="Test body",
        file_path=file_path,
    )


@pytest.fixture
def gate(tmp_vault, monkeypatch):
    """Create an ApprovalGate with short timeouts for testing."""
    monkeypatch.setattr("orchestrator.approval_gate.config.approval.poll_interval_seconds", 0.1)
    monkeypatch.setattr("orchestrator.approval_gate.config.approval.timeout_minutes", 0.05)  # 3 seconds
    monkeypatch.setattr("orchestrator.approval_gate.config.vault.halt_file", tmp_vault / "HALT.md")
    return ApprovalGate()


class TestHaltCheck:
    def test_no_halt(self, gate, tmp_vault):
        assert gate.check_halt() is False

    def test_halt_detected(self, gate, tmp_vault):
        (tmp_vault / "HALT.md").write_text("# HALTED", encoding="utf-8")
        assert gate.check_halt() is True


class TestWaitForApproval:
    def test_approved(self, gate, sample_task_file):
        task = _make_task(sample_task_file)
        # Pre-set to approved
        update_frontmatter(sample_task_file, {"status": "approved"})
        result = gate.wait_for_approval(task)
        assert result == TaskStatus.APPROVED

    def test_rejected(self, gate, sample_task_file):
        task = _make_task(sample_task_file)
        update_frontmatter(sample_task_file, {"status": "rejected"})
        result = gate.wait_for_approval(task)
        assert result == TaskStatus.REJECTED

    def test_timeout(self, gate, sample_task_file):
        task = _make_task(sample_task_file)
        # Status stays awaiting-approval -> should timeout
        with pytest.raises(ApprovalTimeout):
            gate.wait_for_approval(task)

    def test_halt_during_wait(self, gate, sample_task_file, tmp_vault):
        task = _make_task(sample_task_file)

        # Create HALT.md after a short delay
        def create_halt():
            time.sleep(0.2)
            (tmp_vault / "HALT.md").write_text("# HALTED", encoding="utf-8")

        t = threading.Thread(target=create_halt)
        t.start()

        with pytest.raises(SystemHalted):
            gate.wait_for_approval(task)

        t.join()

    def test_delayed_approval(self, gate, sample_task_file):
        task = _make_task(sample_task_file)

        # Approve after a short delay
        def approve_later():
            time.sleep(0.3)
            update_frontmatter(sample_task_file, {"status": "approved"})

        t = threading.Thread(target=approve_later)
        t.start()

        result = gate.wait_for_approval(task)
        assert result == TaskStatus.APPROVED

        t.join()
