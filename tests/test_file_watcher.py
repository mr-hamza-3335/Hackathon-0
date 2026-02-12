"""Tests for file_watcher."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from watchers.file_watcher import InboxHandler
from watchers.utils.markdown_parser import parse_frontmatter


@pytest.fixture
def handler(tmp_vault, monkeypatch):
    """Create an InboxHandler pointed at the tmp vault."""
    monkeypatch.setattr("watchers.file_watcher.INBOX_PATH", tmp_vault / "inbox")
    monkeypatch.setattr("watchers.file_watcher.TASKS_PATH", tmp_vault / "tasks")
    return InboxHandler()


class TestInboxHandler:
    def test_process_valid_task(self, handler, sample_inbox_file, tmp_vault):
        handler._process_task(sample_inbox_file)

        # File should be moved to tasks
        moved = tmp_vault / "tasks" / sample_inbox_file.name
        assert moved.exists()
        assert not sample_inbox_file.exists()

        # Status should be set to pending
        fm, _ = parse_frontmatter(moved)
        assert fm["status"] == "pending"

        # Trigger should exist
        trigger = tmp_vault / "tasks" / ".trigger"
        assert trigger.exists()
        assert trigger.read_text(encoding="utf-8").strip() == "task-test-001"

    def test_process_invalid_task(self, handler, tmp_vault):
        # Create a file without required frontmatter
        bad_file = tmp_vault / "inbox" / "bad-task.md"
        bad_file.write_text("---\npriority: high\n---\n\nNo id or status.", encoding="utf-8")

        handler._process_task(bad_file)

        # File should NOT be moved (stays in inbox)
        assert bad_file.exists()
        moved = tmp_vault / "tasks" / "bad-task.md"
        assert not moved.exists()

    def test_ignores_directories(self, handler):
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/some/dir"
        # Should return without processing
        handler.on_created(event)

    def test_ignores_non_markdown(self, handler):
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/file.txt"
        # Should return without processing
        handler.on_created(event)

    def test_ignores_template_files(self, handler):
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/vault/inbox/_template.md"
        # Should return without processing (starts with _)
        handler.on_created(event)
