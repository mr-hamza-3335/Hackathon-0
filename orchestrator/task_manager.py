"""Task manager — lifecycle state machine for task files.

Manages task state transitions, reads/writes frontmatter,
and moves completed tasks to the archive.
"""

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from watchers.utils.markdown_parser import parse_frontmatter, update_frontmatter
from orchestrator.config import config
from orchestrator.logger import audit


class TaskStatus(str, Enum):
    """Valid task states in the lifecycle."""
    NEW = "new"
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting-approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


# Valid state transitions
TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.NEW: {TaskStatus.PENDING},
    TaskStatus.PENDING: {TaskStatus.PLANNING, TaskStatus.FAILED},
    TaskStatus.PLANNING: {TaskStatus.AWAITING_APPROVAL, TaskStatus.FAILED},
    TaskStatus.AWAITING_APPROVAL: {TaskStatus.APPROVED, TaskStatus.REJECTED},
    TaskStatus.APPROVED: {TaskStatus.EXECUTING},
    TaskStatus.EXECUTING: {TaskStatus.COMPLETED, TaskStatus.FAILED},
    TaskStatus.REJECTED: set(),
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: {TaskStatus.PENDING},  # allow retry
}


@dataclass
class Task:
    """In-memory representation of a vault task file."""
    id: str
    status: TaskStatus
    priority: str
    source: str
    tags: list[str]
    approval_required: bool
    body: str
    file_path: Path
    created: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str:
        stem = self.file_path.stem
        if len(stem) > 11 and stem[10] == "_":
            stem = stem[11:]
        return stem.replace("-", " ").replace("_", " ").title()


class TaskManager:
    """Manages task lifecycle using vault markdown files."""

    def __init__(self) -> None:
        self.tasks_dir = config.vault.tasks
        self.archive_dir = config.vault.archive
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def load_task(self, file_path: Path) -> Task:
        """Load a task from a markdown file."""
        fm, body = parse_frontmatter(file_path)

        return Task(
            id=fm.get("id", file_path.stem),
            status=TaskStatus(fm.get("status", "pending")),
            priority=fm.get("priority", "medium"),
            source=fm.get("source", "unknown"),
            tags=fm.get("tags", []) or [],
            approval_required=fm.get("approval_required", True),
            body=body,
            file_path=file_path,
            created=fm.get("created", ""),
            extra={k: v for k, v in fm.items()
                   if k not in ("id", "status", "priority", "source",
                                "tags", "approval_required", "created")},
        )

    def transition(self, task: Task, new_status: TaskStatus) -> None:
        """Move a task to a new lifecycle state.

        Raises ValueError if the transition is not allowed.
        """
        allowed = TRANSITIONS.get(task.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {task.status.value} -> {new_status.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        old_status = task.status
        task.status = new_status

        update_frontmatter(task.file_path, {
            "status": new_status.value,
            "last_updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

        audit.log_lifecycle(task.id, old_status.value, new_status.value)

    def write_plan(self, task: Task, plan_text: str) -> None:
        """Append the AI-generated plan to the task file."""
        fm, existing_body = parse_frontmatter(task.file_path)

        if "## Proposed Plan" in existing_body:
            existing_body = existing_body[:existing_body.index("## Proposed Plan")].rstrip()

        new_body = existing_body + "\n\n" + plan_text
        yaml_str = yaml.dump(fm, default_flow_style=False, sort_keys=False)
        content = f"---\n{yaml_str}---\n\n{new_body}\n"
        task.file_path.write_text(content, encoding="utf-8")
        task.body = new_body

    def write_result(self, task: Task, result_text: str) -> None:
        """Append execution result to the task file."""
        fm, existing_body = parse_frontmatter(task.file_path)

        if "## Execution Result" in existing_body:
            existing_body = existing_body[:existing_body.index("## Execution Result")].rstrip()

        new_body = existing_body + "\n\n## Execution Result\n\n" + result_text
        yaml_str = yaml.dump(fm, default_flow_style=False, sort_keys=False)
        content = f"---\n{yaml_str}---\n\n{new_body}\n"
        task.file_path.write_text(content, encoding="utf-8")
        task.body = new_body

    def archive_task(self, task: Task) -> Path:
        """Move a completed/failed/rejected task to the archive."""
        dest = self.archive_dir / task.file_path.name
        shutil.move(str(task.file_path), str(dest))
        task.file_path = dest
        return dest

    def get_pending_tasks(self) -> list[Task]:
        """Find all tasks with status 'pending' in the tasks directory."""
        tasks: list[Task] = []
        for md_file in sorted(self.tasks_dir.glob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                task = self.load_task(md_file)
                if task.status == TaskStatus.PENDING:
                    tasks.append(task)
            except Exception as e:
                audit.log_error(md_file.stem, "load-task", str(e))
        return tasks

    def check_trigger(self) -> str | None:
        """Check for and consume a .trigger file from the watcher.

        Returns the task ID if a trigger exists, None otherwise.
        """
        trigger = self.tasks_dir / ".trigger"
        if trigger.exists():
            task_id = trigger.read_text(encoding="utf-8").strip()
            trigger.unlink()
            return task_id
        return None

    def reload_status(self, task: Task) -> TaskStatus:
        """Re-read the task file to get the current status (detects human edits)."""
        fm, _ = parse_frontmatter(task.file_path)
        current = TaskStatus(fm.get("status", task.status.value))
        task.status = current
        return current
