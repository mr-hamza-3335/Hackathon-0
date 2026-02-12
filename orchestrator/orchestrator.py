"""
Unified Orchestrator — Single-file AI Employee engine.

This module provides a clean, self-contained orchestrator that combines
all core functionality into one importable, runnable file. It wraps the
modular components (task_manager, approval_gate, claude_bridge, etc.)
into a simple, demo-friendly interface.

Features:
  - Monitors vault/tasks/ AND vault/approved/ for work
  - Plans tasks using Claude (or simulation fallback)
  - Manages the full task lifecycle with state machine
  - Supports two approval methods:
    1. Frontmatter edit (status: approved)
    2. Folder move (needs_action/ → approved/)
  - Logs every action to vault/logs/
  - Updates vault/dashboard.md in real time
  - Respects HALT.md kill switch
  - Clean error handling and graceful shutdown

Usage:
    python -m orchestrator.orchestrator          # Run the orchestrator
    python orchestrator/orchestrator.py          # Direct execution

Architecture:
    This file delegates to the modular components:
    - config.py       → Configuration
    - task_manager.py  → Task lifecycle
    - approval_gate.py → Human approval
    - claude_bridge.py → AI reasoning
    - action_dispatcher.py → MCP tool execution
    - dashboard.py     → Live status dashboard
    - logger.py        → Audit logging
"""

import logging
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup — ensure project root is importable
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Imports from modular components
# ---------------------------------------------------------------------------

from orchestrator.config import config
from orchestrator.logger import audit, console
from orchestrator.task_manager import TaskManager, TaskStatus, Task
from orchestrator.approval_gate import (
    ApprovalGate, ApprovalTimeout, SystemHalted,
)
from orchestrator.claude_bridge import generate_plan
from orchestrator.action_dispatcher import (
    ActionDispatcher, format_results_markdown,
)
from orchestrator.dashboard import DashboardUpdater
from watchers.utils.markdown_parser import (
    parse_frontmatter, update_frontmatter,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orchestrator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BANNER = r"""
  ╔══════════════════════════════════════════════════════════════╗
  ║           PERSONAL AI EMPLOYEE — ORCHESTRATOR               ║
  ║              Plan → Approve → Execute → Log                 ║
  ╚══════════════════════════════════════════════════════════════╝
"""

# Approval workflow folders
NEEDS_ACTION_DIR = config.vault.root / "needs_action"
APPROVED_DIR = config.vault.root / "approved"
COMPLETED_DIR = config.vault.root / "completed"


# ---------------------------------------------------------------------------
# Orchestrator Engine
# ---------------------------------------------------------------------------

class AIEmployeeOrchestrator:
    """
    The main AI Employee engine.

    Lifecycle:
        1. Poll for new tasks (pending in vault/tasks/)
        2. Poll for approved tasks (moved to vault/approved/)
        3. For pending tasks: generate plan → move to needs_action
        4. For approved tasks: execute → log → move to completed
        5. Update dashboard every cycle
        6. Repeat until HALT.md or Ctrl+C
    """

    def __init__(self) -> None:
        self.task_mgr = TaskManager()
        self.gate = ApprovalGate()
        self.dispatcher = ActionDispatcher()
        self.dashboard = DashboardUpdater()
        self.poll_interval = config.orchestrator.poll_interval_seconds
        self.halt_file = config.vault.halt_file
        self._running = True

        # Ensure all workflow directories exist
        for d in (NEEDS_ACTION_DIR, APPROVED_DIR, COMPLETED_DIR):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the orchestrator main loop."""
        print(BANNER)
        self._log_startup()
        audit.log_system("orchestrator-started")
        self.dashboard.update(orchestrator_status="Running")

        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("\nShutting down (Ctrl+C)...")
        finally:
            audit.log_system("orchestrator-stopped")
            self.dashboard.update(orchestrator_status="Stopped")
            logger.info("Orchestrator stopped.")

    def _main_loop(self) -> None:
        """Core polling loop."""
        while self._running:
            try:
                # Step 1: Check kill switch
                if self._check_halt():
                    continue

                # Step 2: Consume any watcher triggers
                trigger_id = self.task_mgr.check_trigger()
                if trigger_id:
                    logger.info(f"Trigger received: {trigger_id}")

                # Step 3: Process pending tasks (need planning)
                pending = self.task_mgr.get_pending_tasks()
                for task in pending:
                    self._plan_task(task)
                    if self.halt_file.exists():
                        break

                # Step 4: Check for folder-approved tasks
                self._check_approved_folder()

                # Step 5: Check for frontmatter-approved tasks
                self._check_frontmatter_approvals()

                # Step 6: Update dashboard
                self.dashboard.update(orchestrator_status="Running")

            except SystemHalted:
                logger.warning("System HALTED — pausing")
                self.dashboard.update(orchestrator_status="HALTED")

            except Exception as e:
                logger.exception(f"Error in main loop: {e}")
                audit.log_error("system", "main-loop-error", str(e))

            time.sleep(self.poll_interval)

    # ------------------------------------------------------------------
    # Phase 1: Planning
    # ------------------------------------------------------------------

    def _plan_task(self, task: Task) -> None:
        """Generate an AI plan for a pending task."""
        logger.info("")
        logger.info(f"{'='*60}")
        logger.info(f"PLANNING: {task.title} ({task.id})")
        logger.info(f"{'='*60}")

        try:
            # Transition to planning
            self.task_mgr.transition(task, TaskStatus.PLANNING)
            self.dashboard.update(orchestrator_status="Planning")

            # Generate plan via Claude (or simulation)
            plan_text = generate_plan(task.body)
            self.task_mgr.write_plan(task, plan_text)

            audit.log_action(
                task_id=task.id,
                action="generate-plan",
                tool="claude",
                input_summary=f"Task: {task.title}",
                output_summary=f"Plan: {len(plan_text)} chars",
                status="success",
            )

            # Move to awaiting-approval
            self.task_mgr.transition(task, TaskStatus.AWAITING_APPROVAL)

            # Also copy to needs_action folder for folder-based approval
            needs_action_copy = NEEDS_ACTION_DIR / task.file_path.name
            shutil.copy2(str(task.file_path), str(needs_action_copy))

            logger.info(f"Plan ready — awaiting approval")
            logger.info(f"  Option 1: Edit status to 'approved' in the task file")
            logger.info(f"  Option 2: Move from needs_action/ to approved/")
            logger.info("")

        except Exception as e:
            logger.error(f"Planning failed for {task.id}: {e}")
            audit.log_error(task.id, "planning-failed", str(e))
            try:
                self.task_mgr.transition(task, TaskStatus.FAILED)
                self.task_mgr.archive_task(task)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Phase 2: Approval Detection
    # ------------------------------------------------------------------

    def _check_approved_folder(self) -> None:
        """Check vault/approved/ for files moved there by the user."""
        for md_file in APPROVED_DIR.glob("*.md"):
            if md_file.name.startswith("_"):
                continue

            logger.info(f"Folder-approved task found: {md_file.name}")

            try:
                # Update frontmatter
                update_frontmatter(md_file, {"status": "approved"})

                # Load as task
                task = self.task_mgr.load_task(md_file)
                task.status = TaskStatus.APPROVED

                # Remove the copy from needs_action if it exists
                needs_copy = NEEDS_ACTION_DIR / md_file.name
                if needs_copy.exists():
                    needs_copy.unlink()

                # Remove the original from vault/tasks/ if it exists
                tasks_copy = config.vault.tasks / md_file.name
                if tasks_copy.exists():
                    tasks_copy.unlink()

                # Execute the approved task
                self._execute_task(task)

                # Move to completed folder
                completed_dest = COMPLETED_DIR / md_file.name
                if task.file_path.exists():
                    shutil.move(str(task.file_path), str(completed_dest))
                elif md_file.exists():
                    shutil.move(str(md_file), str(completed_dest))

            except Exception as e:
                logger.error(f"Failed to process approved file: {e}")
                audit.log_error(md_file.stem, "approval-processing", str(e))

    def _check_frontmatter_approvals(self) -> None:
        """Check vault/tasks/ for files with status: approved."""
        for md_file in config.vault.tasks.glob("*.md"):
            if md_file.name.startswith("_"):
                continue

            try:
                fm, _ = parse_frontmatter(md_file)
                if fm.get("status") != "approved":
                    continue

                logger.info(f"Frontmatter-approved task: {md_file.name}")
                task = self.task_mgr.load_task(md_file)

                # Remove needs_action copy
                needs_copy = NEEDS_ACTION_DIR / md_file.name
                if needs_copy.exists():
                    needs_copy.unlink()

                # Execute
                self._execute_task(task)

                # Archive
                self.task_mgr.archive_task(task)

                # Also copy to completed
                completed_dest = COMPLETED_DIR / md_file.name
                if task.file_path.exists() and not completed_dest.exists():
                    shutil.copy2(str(task.file_path), str(completed_dest))

            except Exception as e:
                logger.error(f"Failed to process {md_file.name}: {e}")

    # ------------------------------------------------------------------
    # Phase 3: Execution
    # ------------------------------------------------------------------

    def _execute_task(self, task: Task) -> None:
        """Execute an approved task's plan steps via MCP."""
        logger.info("")
        logger.info(f"{'='*60}")
        logger.info(f"EXECUTING: {task.title}")
        logger.info(f"{'='*60}")

        try:
            # Update status
            if task.status != TaskStatus.EXECUTING:
                try:
                    self.task_mgr.transition(task, TaskStatus.EXECUTING)
                except ValueError:
                    # May already be in a compatible state from folder workflow
                    update_frontmatter(task.file_path, {"status": "executing"})
                    task.status = TaskStatus.EXECUTING

            self.dashboard.update(orchestrator_status="Executing")

            # Parse and execute plan steps
            steps = self.dispatcher.parse_plan_steps(task.body)
            logger.info(f"Executing {len(steps)} plan step(s)")

            if steps:
                results = self.dispatcher.execute_steps(steps)
                results_md = format_results_markdown(results)
                self.task_mgr.write_result(task, results_md)

                # Log each action
                for r in results:
                    audit.log_action(
                        task_id=task.id,
                        action=f"execute-{r.tool}",
                        tool=r.tool,
                        input_summary=r.step[:60],
                        output_summary=r.output,
                        status=r.status,
                        error=r.error,
                        duration_ms=r.duration_ms,
                    )

                failures = [r for r in results if r.status == "failure"]
                if failures:
                    raise RuntimeError(
                        f"{len(failures)} step(s) failed"
                    )

            # Mark complete
            update_frontmatter(task.file_path, {"status": "completed"})
            task.status = TaskStatus.COMPLETED

            audit.log_action(
                task_id=task.id,
                action="task-completed",
                tool="orchestrator",
                output_summary=f"'{task.title}' completed",
                status="success",
            )

            logger.info(f"COMPLETED: {task.title}")
            logger.info("")

        except Exception as e:
            logger.error(f"Execution failed: {e}")
            audit.log_error(task.id, "execution-failed", str(e))
            update_frontmatter(task.file_path, {"status": "failed"})

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _check_halt(self) -> bool:
        """Check HALT.md kill switch."""
        if self.halt_file.exists():
            logger.warning("HALT.md detected — system paused")
            self.dashboard.update(orchestrator_status="HALTED")
            while self.halt_file.exists():
                time.sleep(2)
            logger.info("HALT.md removed — resuming")
            self.dashboard.update(orchestrator_status="Running")
            audit.log_system("halt-released")
            return True
        return False

    def _log_startup(self) -> None:
        """Log startup information."""
        logger.info("Orchestrator starting...")
        logger.info(f"  Vault:       {config.vault.root.resolve()}")
        logger.info(f"  Tasks:       {config.vault.tasks.resolve()}")
        logger.info(f"  Needs Action:{NEEDS_ACTION_DIR.resolve()}")
        logger.info(f"  Approved:    {APPROVED_DIR.resolve()}")
        logger.info(f"  Completed:   {COMPLETED_DIR.resolve()}")
        logger.info(f"  Logs:        {config.vault.logs.resolve()}")
        logger.info(f"  Poll:        {self.poll_interval}s")
        logger.info(f"  HALT file:   {self.halt_file}")
        logger.info("")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the AI Employee orchestrator."""
    engine = AIEmployeeOrchestrator()
    engine.run()


if __name__ == "__main__":
    main()
