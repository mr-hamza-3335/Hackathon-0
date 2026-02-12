"""Shared fixtures for AI Employee tests."""

import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a temporary vault structure for testing."""
    inbox = tmp_path / "inbox"
    tasks = tmp_path / "tasks"
    archive = tasks / "archive"
    logs = tmp_path / "logs"
    context = tmp_path / "context"

    for d in (inbox, tasks, archive, logs, context):
        d.mkdir(parents=True)

    return tmp_path


@pytest.fixture
def sample_task_content():
    """Return valid task markdown content."""
    return """---
id: task-test-001
status: pending
priority: high
source: manual
tags: [test, unit]
approval_required: true
created: 2026-02-12T12:00:00
---

## Request

This is a test task for unit testing.

## Context

Testing the AI Employee system.
"""


@pytest.fixture
def sample_task_file(tmp_vault, sample_task_content):
    """Create a sample task file in the tmp vault tasks dir."""
    task_file = tmp_vault / "tasks" / "2026-02-12_test-task.md"
    task_file.write_text(sample_task_content, encoding="utf-8")
    return task_file


@pytest.fixture
def sample_inbox_file(tmp_vault, sample_task_content):
    """Create a sample task file in the tmp vault inbox."""
    inbox_file = tmp_vault / "inbox" / "2026-02-12_test-task.md"
    inbox_file.write_text(sample_task_content, encoding="utf-8")
    return inbox_file
