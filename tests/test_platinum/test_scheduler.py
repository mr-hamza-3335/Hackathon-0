"""Tests for Platinum tier scheduler."""

import time
import pytest
from platinum.scheduler.scheduler import TaskScheduler, ScheduledTask, ScheduleType


@pytest.fixture
def scheduler():
    s = TaskScheduler()
    yield s
    s.stop_worker()


class TestScheduler:
    def test_schedule_once(self, scheduler):
        task_id = scheduler.schedule_once("t1", "Test Task", delay_seconds=60)
        assert task_id == "t1"
        tasks = scheduler.get_scheduled_tasks()
        assert len(tasks) == 1
        assert tasks[0]["name"] == "Test Task"

    def test_schedule_interval(self, scheduler):
        task_id = scheduler.schedule_interval(
            "t2", "Recurring", interval_seconds=300, max_runs=5,
        )
        tasks = scheduler.get_scheduled_tasks()
        assert len(tasks) == 1
        assert tasks[0]["schedule_type"] == "interval"

    def test_cancel_task(self, scheduler):
        scheduler.schedule_once("t3", "Cancel Me", delay_seconds=60)
        assert scheduler.cancel("t3") is True
        assert len(scheduler.get_scheduled_tasks()) == 0

    def test_cancel_nonexistent(self, scheduler):
        assert scheduler.cancel("nope") is False

    def test_worker_starts_and_stops(self, scheduler):
        scheduler.start_worker()
        status = scheduler.get_worker_status()
        assert status["running"] is True

        scheduler.stop_worker()
        status = scheduler.get_worker_status()
        assert status["running"] is False

    def test_execute_due_task(self, scheduler):
        executed = []

        def callback():
            executed.append(True)

        scheduler.schedule_once("t4", "Immediate", delay_seconds=0, callback=callback)
        scheduler.start_worker()
        time.sleep(2)  # Give worker time to pick up the task
        scheduler.stop_worker()

        assert len(executed) >= 1

    def test_retry_on_failure(self, scheduler):
        call_count = []

        def failing_callback():
            call_count.append(1)
            raise RuntimeError("Simulated failure")

        task = ScheduledTask(
            id="retry-test", name="Retry Test",
            schedule_type=ScheduleType.ONCE,
            callback=failing_callback,
            max_retries=2,
            retry_delay_seconds=1,
        )
        scheduler.schedule(task)
        scheduler.start_worker()
        time.sleep(5)  # Allow retries
        scheduler.stop_worker()

        # Should have tried at least twice (initial + 1 retry)
        assert len(call_count) >= 2

    def test_worker_status(self, scheduler):
        scheduler.start_worker()
        time.sleep(0.5)
        status = scheduler.get_worker_status()
        assert status["running"] is True
        assert status["uptime_seconds"] > 0
        scheduler.stop_worker()
