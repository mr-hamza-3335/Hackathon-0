"""Approval gate — pauses execution until human approves via Obsidian.

The gate polls the task file's YAML frontmatter for status changes.
The human edits the status field in Obsidian to 'approved' or 'rejected'.
"""

import time
import logging

from orchestrator.config import config
from orchestrator.task_manager import Task, TaskStatus
from watchers.utils.markdown_parser import parse_frontmatter

logger = logging.getLogger("orchestrator.approval")


class ApprovalTimeout(Exception):
    """Raised when approval wait exceeds the configured timeout."""


class SystemHalted(Exception):
    """Raised when HALT.md is detected during approval wait."""


class ApprovalGate:
    """Polls task frontmatter waiting for human approval."""

    def __init__(self) -> None:
        self.poll_interval = config.approval.poll_interval_seconds
        self.timeout_seconds = config.approval.timeout_minutes * 60
        self.halt_file = config.vault.halt_file

    def check_halt(self) -> bool:
        """Check if the kill switch is active."""
        return self.halt_file.exists()

    def wait_for_approval(self, task: Task) -> TaskStatus:
        """Block until the task is approved, rejected, or times out.

        The human edits the task file in Obsidian, changing the
        frontmatter status to 'approved' or 'rejected'.

        Returns:
            TaskStatus.APPROVED or TaskStatus.REJECTED

        Raises:
            SystemHalted: if HALT.md appears during wait
            ApprovalTimeout: if timeout is exceeded
        """
        elapsed = 0
        task_name = task.title
        last_log_at = 0

        logger.info(
            f"AWAITING APPROVAL: \"{task_name}\" "
            f"-> Edit status to 'approved' in Obsidian"
        )
        logger.info(f"  Task file: {task.file_path}")

        while elapsed < self.timeout_seconds:
            # Check kill switch
            if self.check_halt():
                logger.warning("HALT.md detected — stopping approval wait")
                raise SystemHalted("System halted by HALT.md")

            # Re-read the task file to see if human changed status
            fm, _ = parse_frontmatter(task.file_path)
            current_status = fm.get("status", "")

            if current_status == TaskStatus.APPROVED.value:
                task.status = TaskStatus.APPROVED
                logger.info(f"APPROVED: {task_name}")
                return TaskStatus.APPROVED

            if current_status == TaskStatus.REJECTED.value:
                task.status = TaskStatus.REJECTED
                logger.info(f"REJECTED: {task_name}")
                return TaskStatus.REJECTED

            # Progress indicator every 15 seconds
            if elapsed - last_log_at >= 15:
                last_log_at = elapsed
                remaining = (self.timeout_seconds - elapsed) // 60
                logger.info(
                    f"  ... waiting for approval ({remaining}m remaining)"
                )

            time.sleep(self.poll_interval)
            elapsed += self.poll_interval

        raise ApprovalTimeout(
            f"Approval timeout after {config.approval.timeout_minutes}m "
            f"for task {task.id}"
        )
