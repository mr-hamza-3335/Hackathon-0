"""Main orchestrator loop — the Bronze-tier AI Employee engine.

This is the entry point. It runs a continuous poll loop that:
1. Checks the HALT kill switch
2. Scans for trigger files from the watcher
3. Loads pending tasks
4. For each task: plan -> propose -> await approval -> execute -> log
5. Updates the dashboard after every cycle

Usage:
    python -m orchestrator.run
"""

import logging
import sys
import time
from pathlib import Path

from orchestrator.config import config
from orchestrator.logger import audit
from orchestrator.task_manager import TaskManager, TaskStatus, Task
from orchestrator.approval_gate import ApprovalGate, ApprovalTimeout, SystemHalted
from orchestrator.ai_bridge import generate_plan
from orchestrator.action_dispatcher import ActionDispatcher, format_results_markdown
from orchestrator.dashboard import DashboardUpdater

logger = logging.getLogger("orchestrator")

# ── ASCII Banner ──────────────────────────────────────────────────────────────

BANNER = r"""
  ╔══════════════════════════════════════════════════════════════╗
  ║            PERSONAL AI EMPLOYEE — BRONZE MVP                ║
  ║                  Orchestrator Engine                        ║
  ╚══════════════════════════════════════════════════════════════╝
"""


class Orchestrator:
    """Main orchestrator engine — ties all components together."""

    def __init__(self) -> None:
        self.task_mgr = TaskManager()
        self.gate = ApprovalGate()
        self.dispatcher = ActionDispatcher()
        self.dashboard = DashboardUpdater()
        self.poll_interval = config.orchestrator.poll_interval_seconds
        self.halt_file = config.vault.halt_file
        self._running = True

    # ── Main Loop ─────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the orchestrator main loop."""
        print(BANNER)
        logger.info("Orchestrator starting...")
        logger.info(f"  Vault:     {config.vault.root.resolve()}")
        logger.info(f"  Tasks dir: {config.vault.tasks.resolve()}")
        logger.info(f"  Logs dir:  {config.vault.logs.resolve()}")
        logger.info(f"  Poll:      {self.poll_interval}s")
        logger.info(f"  HALT file: {self.halt_file}")
        logger.info("")

        audit.log_system("orchestrator-started")
        self.dashboard.update(orchestrator_status="Running")

        try:
            self._loop()
        except KeyboardInterrupt:
            logger.info("")
            logger.info("Shutting down (Ctrl+C)...")
        finally:
            audit.log_system("orchestrator-stopped")
            self.dashboard.update(orchestrator_status="Stopped")
            logger.info("Orchestrator stopped.")

    def _loop(self) -> None:
        """Core poll loop."""
        while self._running:
            try:
                # ── Step 1: Check kill switch ──
                if self._check_halt():
                    continue

                # ── Step 2: Check for watcher triggers ──
                trigger_id = self.task_mgr.check_trigger()
                if trigger_id:
                    logger.info(f"Trigger received: {trigger_id}")

                # ── Step 3: Find pending tasks ──
                tasks = self.task_mgr.get_pending_tasks()
                if tasks:
                    logger.info(f"Found {len(tasks)} pending task(s)")

                # ── Step 4: Process tasks one at a time (Bronze) ──
                for task in tasks:
                    self._process_task(task)

                    # Re-check halt between tasks
                    if self.halt_file.exists():
                        break

                # ── Step 5: Update dashboard ──
                self.dashboard.update(orchestrator_status="Running")

            except SystemHalted:
                logger.warning("System HALTED — pausing all processing")
                self.dashboard.update(orchestrator_status="HALTED")

            except Exception as e:
                logger.exception(f"Unexpected error in main loop: {e}")
                audit.log_error("system", "main-loop-error", str(e))

            # Sleep before next poll
            time.sleep(self.poll_interval)

    # ── Task Processing Pipeline ──────────────────────────────────────────

    def _process_task(self, task: Task) -> None:
        """Run a single task through the full lifecycle."""
        logger.info("")
        logger.info(f"{'='*60}")
        logger.info(f"PROCESSING: {task.title} ({task.id})")
        logger.info(f"  Priority: {task.priority}")
        logger.info(f"  Source:   {task.source}")
        logger.info(f"  File:     {task.file_path.name}")
        logger.info(f"{'='*60}")

        try:
            # ── Phase 1: Planning ──
            self._phase_plan(task)

            # ── Phase 2: Await Approval ──
            approved = self._phase_approve(task)
            if not approved:
                return

            # ── Phase 3: Execute ──
            self._phase_execute(task)

            # ── Phase 4: Complete ──
            self._phase_complete(task)

        except SystemHalted:
            logger.warning(f"Task {task.id} interrupted by HALT")
            raise

        except ApprovalTimeout:
            logger.warning(f"Task {task.id} timed out waiting for approval")
            audit.log_error(task.id, "approval-timeout", "Timed out")
            self.task_mgr.transition(task, TaskStatus.FAILED)
            self.task_mgr.archive_task(task)

        except Exception as e:
            logger.error(f"Task {task.id} FAILED: {e}")
            audit.log_error(task.id, "task-processing-error", str(e))
            try:
                self.task_mgr.transition(task, TaskStatus.FAILED)
                self.task_mgr.write_result(task, f"**Error**: {e}")
                self.task_mgr.archive_task(task)
            except Exception:
                logger.exception("Failed to update task status after error")

    def _phase_plan(self, task: Task) -> None:
        """Phase 1: Use Claude to generate a plan."""
        logger.info("")
        logger.info("[Phase 1] PLANNING...")

        self.task_mgr.transition(task, TaskStatus.PLANNING)
        self.dashboard.update(orchestrator_status="Planning")

        # Call Claude for reasoning
        plan_text = generate_plan(task.body)

        # Write plan into task file
        self.task_mgr.write_plan(task, plan_text)
        logger.info("Plan written to task file")

        audit.log_action(
            task_id=task.id,
            action="generate-plan",
            tool="claude",
            input_summary=f"Task: {task.title}",
            output_summary=f"Plan generated ({len(plan_text)} chars)",
            status="success",
        )

    def _phase_approve(self, task: Task) -> bool:
        """Phase 2: Wait for human approval in Obsidian.

        Returns True if approved, False if rejected.
        """
        logger.info("")
        logger.info("[Phase 2] AWAITING APPROVAL...")
        logger.info("  >> Open the task file in Obsidian")
        logger.info("  >> Review the Proposed Plan and Draft Output")
        logger.info("  >> Change frontmatter status to: approved")
        logger.info("")

        self.task_mgr.transition(task, TaskStatus.AWAITING_APPROVAL)
        self.dashboard.update(orchestrator_status="Awaiting Approval")

        result = self.gate.wait_for_approval(task)

        if result == TaskStatus.REJECTED:
            logger.info("Task REJECTED by user")
            audit.log_action(
                task_id=task.id,
                action="approval-rejected",
                tool="human",
                status="success",
                output_summary="User rejected the proposed plan",
            )
            self.task_mgr.archive_task(task)
            return False

        return True

    def _phase_execute(self, task: Task) -> None:
        """Phase 3: Execute approved plan steps."""
        logger.info("")
        logger.info("[Phase 3] EXECUTING...")

        self.task_mgr.transition(task, TaskStatus.EXECUTING)
        self.dashboard.update(orchestrator_status="Executing")

        # Parse plan steps from the task body
        steps = self.dispatcher.parse_plan_steps(task.body)
        logger.info(f"Found {len(steps)} plan step(s) to execute")

        if not steps:
            logger.info("No actionable steps found — marking complete")
            return

        # Execute steps
        results = self.dispatcher.execute_steps(steps)

        # Write results to task file
        results_md = format_results_markdown(results)
        self.task_mgr.write_result(task, results_md)

        # Log each action
        for r in results:
            audit.log_action(
                task_id=task.id,
                action=f"execute:{r.step[:50]}",
                tool=r.tool,
                input_summary=r.step,
                output_summary=r.output,
                status=r.status,
                error=r.error,
                duration_ms=r.duration_ms,
            )

        # Check if any step failed
        failures = [r for r in results if r.status == "failure"]
        if failures:
            raise RuntimeError(
                f"{len(failures)} step(s) failed: "
                + "; ".join(f.error for f in failures)
            )

    def _phase_complete(self, task: Task) -> None:
        """Phase 4: Mark task complete and archive."""
        logger.info("")
        logger.info("[Phase 4] COMPLETING...")

        self.task_mgr.transition(task, TaskStatus.COMPLETED)
        self.task_mgr.archive_task(task)

        audit.log_action(
            task_id=task.id,
            action="task-completed",
            tool="orchestrator",
            output_summary=f"Task '{task.title}' completed and archived",
            status="success",
        )

        logger.info(f"Task COMPLETED: {task.title}")
        logger.info(f"Archived to: {task.file_path}")
        logger.info("")

    # ── Utilities ─────────────────────────────────────────────────────────

    def _check_halt(self) -> bool:
        """Check for HALT.md kill switch. Returns True if halted."""
        if self.halt_file.exists():
            logger.warning("HALT.md detected — system paused")
            self.dashboard.update(orchestrator_status="HALTED")
            # Wait until HALT.md is removed
            while self.halt_file.exists():
                time.sleep(2)
            logger.info("HALT.md removed — resuming")
            self.dashboard.update(orchestrator_status="Running")
            audit.log_system("halt-released")
            return True
        return False


# ── Entry Point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Entry point for the orchestrator."""
    engine = Orchestrator()
    engine.run()


if __name__ == "__main__":
    main()
