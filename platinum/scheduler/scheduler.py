"""Task Scheduler — Platinum tier autonomous mode.

Provides:
- Scheduled/recurring tasks
- Background worker loops
- Retry logic with exponential backoff
- Cron-like scheduling
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable
from enum import Enum

logger = logging.getLogger("platinum.scheduler")


class ScheduleType(str, Enum):
    ONCE = "once"
    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"
    CRON = "cron"


@dataclass
class ScheduledTask:
    """A task scheduled for future or recurring execution."""
    id: str
    name: str
    schedule_type: ScheduleType
    callback: Callable[[], Any] | None = None  # None for vault-based tasks
    task_template: dict[str, Any] | None = None  # For creating vault tasks
    interval_seconds: int = 0
    cron_expression: str = ""
    next_run: str = ""
    last_run: str = ""
    run_count: int = 0
    max_runs: int = 0  # 0 = unlimited
    enabled: bool = True
    retry_count: int = 0
    max_retries: int = 3
    retry_delay_seconds: int = 30
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class WorkerStatus:
    """Status of the background worker."""
    running: bool = False
    tasks_processed: int = 0
    tasks_failed: int = 0
    uptime_seconds: float = 0
    last_error: str = ""
    started_at: str = ""


class TaskScheduler:
    """Manages scheduled and recurring tasks."""

    def __init__(self) -> None:
        self._scheduled: dict[str, ScheduledTask] = {}
        self._worker_thread: threading.Thread | None = None
        self._running = False
        self._status = WorkerStatus()
        self._lock = threading.Lock()

    def schedule(self, task: ScheduledTask) -> str:
        """Schedule a task for execution."""
        if not task.next_run:
            task.next_run = self._calculate_next_run(task)

        with self._lock:
            self._scheduled[task.id] = task

        logger.info(f"Task scheduled: {task.name} ({task.schedule_type}) — next run: {task.next_run}")
        return task.id

    def schedule_once(self, task_id: str, name: str, delay_seconds: int,
                     callback: Callable | None = None,
                     task_template: dict | None = None) -> str:
        """Schedule a one-time task."""
        next_run = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
        task = ScheduledTask(
            id=task_id, name=name,
            schedule_type=ScheduleType.ONCE,
            callback=callback,
            task_template=task_template,
            next_run=next_run,
            max_runs=1,
        )
        return self.schedule(task)

    def schedule_interval(self, task_id: str, name: str, interval_seconds: int,
                         callback: Callable | None = None,
                         task_template: dict | None = None,
                         max_runs: int = 0) -> str:
        """Schedule a recurring task at a fixed interval."""
        task = ScheduledTask(
            id=task_id, name=name,
            schedule_type=ScheduleType.INTERVAL,
            callback=callback,
            task_template=task_template,
            interval_seconds=interval_seconds,
            max_runs=max_runs,
        )
        return self.schedule(task)

    def cancel(self, task_id: str) -> bool:
        """Cancel a scheduled task."""
        with self._lock:
            if task_id in self._scheduled:
                del self._scheduled[task_id]
                logger.info(f"Task cancelled: {task_id}")
                return True
        return False

    def get_scheduled_tasks(self) -> list[dict[str, Any]]:
        """List all scheduled tasks."""
        with self._lock:
            return [
                {
                    "id": t.id,
                    "name": t.name,
                    "schedule_type": t.schedule_type,
                    "next_run": t.next_run,
                    "last_run": t.last_run,
                    "run_count": t.run_count,
                    "enabled": t.enabled,
                }
                for t in self._scheduled.values()
            ]

    # ── Background Worker ────────────────────────────────────────────

    def start_worker(self) -> None:
        """Start the background worker loop."""
        if self._running:
            logger.warning("Worker already running")
            return

        self._running = True
        self._status.running = True
        self._status.started_at = datetime.now(timezone.utc).isoformat()

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="platinum-scheduler",
        )
        self._worker_thread.start()
        logger.info("Scheduler worker started")

    def stop_worker(self) -> None:
        """Stop the background worker."""
        self._running = False
        self._status.running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=10)
        logger.info("Scheduler worker stopped")

    def get_worker_status(self) -> dict[str, Any]:
        """Get worker status."""
        if self._status.started_at:
            start = datetime.fromisoformat(self._status.started_at)
            self._status.uptime_seconds = (datetime.now(timezone.utc) - start).total_seconds()
        return {
            "running": self._status.running,
            "tasks_processed": self._status.tasks_processed,
            "tasks_failed": self._status.tasks_failed,
            "uptime_seconds": self._status.uptime_seconds,
            "last_error": self._status.last_error,
            "scheduled_count": len(self._scheduled),
        }

    def _worker_loop(self) -> None:
        """Main worker loop — checks and executes due tasks."""
        logger.info("Worker loop started")
        while self._running:
            try:
                self._check_due_tasks()
            except Exception as e:
                self._status.last_error = str(e)
                logger.error(f"Worker error: {e}")
            time.sleep(1)  # Check every second

    def _check_due_tasks(self) -> None:
        """Check for tasks that are due for execution."""
        now = datetime.now(timezone.utc)

        with self._lock:
            due_tasks = [
                t for t in self._scheduled.values()
                if t.enabled and t.next_run and
                datetime.fromisoformat(t.next_run) <= now
            ]

        for task in due_tasks:
            self._execute_scheduled_task(task)

    def _execute_scheduled_task(self, task: ScheduledTask) -> None:
        """Execute a scheduled task with retry logic."""
        logger.info(f"Executing scheduled task: {task.name}")

        try:
            if task.callback:
                task.callback()

            task.last_run = datetime.now(timezone.utc).isoformat()
            task.run_count += 1
            task.retry_count = 0
            self._status.tasks_processed += 1

            # Calculate next run
            if task.max_runs > 0 and task.run_count >= task.max_runs:
                with self._lock:
                    task.enabled = False
                logger.info(f"Task {task.name} reached max runs ({task.max_runs})")
            else:
                task.next_run = self._calculate_next_run(task)

        except Exception as e:
            logger.error(f"Scheduled task failed: {task.name} — {e}")
            task.retry_count += 1
            self._status.tasks_failed += 1

            if task.retry_count < task.max_retries:
                # Exponential backoff
                delay = task.retry_delay_seconds * (2 ** (task.retry_count - 1))
                task.next_run = (
                    datetime.now(timezone.utc) + timedelta(seconds=delay)
                ).isoformat()
                logger.info(f"Retry {task.retry_count}/{task.max_retries} in {delay}s")
            else:
                task.enabled = False
                self._status.last_error = f"{task.name}: {e}"
                logger.error(f"Task {task.name} failed after {task.max_retries} retries")

    def _calculate_next_run(self, task: ScheduledTask) -> str:
        """Calculate the next run time for a task."""
        now = datetime.now(timezone.utc)

        if task.schedule_type == ScheduleType.ONCE:
            if not task.next_run:
                return now.isoformat()
            return task.next_run

        elif task.schedule_type == ScheduleType.INTERVAL:
            return (now + timedelta(seconds=task.interval_seconds)).isoformat()

        elif task.schedule_type == ScheduleType.DAILY:
            return (now + timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0
            ).isoformat()

        elif task.schedule_type == ScheduleType.WEEKLY:
            return (now + timedelta(weeks=1)).replace(
                hour=9, minute=0, second=0, microsecond=0
            ).isoformat()

        return (now + timedelta(hours=1)).isoformat()


# Singleton
scheduler = TaskScheduler()
