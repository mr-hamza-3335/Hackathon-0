"""
Watchdog Supervisor — Process manager for the AI Employee system.

Manages the lifecycle of all system components:
  - File Watcher (monitors vault/inbox/ for new tasks)
  - Orchestrator (plans, approves, executes tasks)
  - Approval Folder Watcher (monitors vault/approved/ for folder-based approvals)

Features:
  - Starts/stops all processes with a single command
  - Monitors process health and restarts on crash
  - Respects HALT.md kill switch
  - Cross-platform (Windows + Unix)
  - Clean shutdown on Ctrl+C

Usage:
    python -m watchdog.watchdog              # Start all components
    python -m watchdog.watchdog --stop       # Stop all components
    python -m watchdog.watchdog --status     # Check component status
"""

import argparse
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
VAULT_ROOT = PROJECT_ROOT / "vault"
HALT_FILE = VAULT_ROOT / "HALT.md"
PID_DIR = PROJECT_ROOT / ".pids"
LOG_DIR = VAULT_ROOT / "logs"

# Folders for the approval workflow
INBOX_DIR = VAULT_ROOT / "inbox"
NEEDS_ACTION_DIR = VAULT_ROOT / "needs_action"
APPROVED_DIR = VAULT_ROOT / "approved"
COMPLETED_DIR = VAULT_ROOT / "completed"
TASKS_DIR = VAULT_ROOT / "tasks"

POLL_INTERVAL = 3  # seconds between health checks
RESTART_DELAY = 5  # seconds before restarting a crashed process

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("watchdog")

# ---------------------------------------------------------------------------
# ASCII Banner
# ---------------------------------------------------------------------------

BANNER = r"""
  ╔══════════════════════════════════════════════════════════════╗
  ║         PERSONAL AI EMPLOYEE — WATCHDOG SUPERVISOR          ║
  ║                    Managing All Systems                     ║
  ╚══════════════════════════════════════════════════════════════╝
"""


# ---------------------------------------------------------------------------
# Process Management
# ---------------------------------------------------------------------------

class ManagedProcess:
    """Represents a managed subprocess with health monitoring."""

    def __init__(self, name: str, command: list[str], cwd: Path) -> None:
        self.name = name
        self.command = command
        self.cwd = cwd
        self.process: Optional[subprocess.Popen] = None
        self.restart_count = 0
        self.max_restarts = 5
        self.pid_file = PID_DIR / f"{name}.pid"

    def start(self) -> bool:
        """Start the subprocess."""
        if self.is_running():
            logger.info(f"  {self.name}: already running (PID {self.process.pid})")
            return True

        try:
            # Use CREATE_NEW_PROCESS_GROUP on Windows for clean shutdown
            kwargs = {}
            if platform.system() == "Windows":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

            self.process = subprocess.Popen(
                self.command,
                cwd=str(self.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                **kwargs,
            )

            # Save PID
            PID_DIR.mkdir(parents=True, exist_ok=True)
            self.pid_file.write_text(str(self.process.pid), encoding="utf-8")

            logger.info(f"  {self.name}: started (PID {self.process.pid})")
            return True

        except FileNotFoundError as e:
            logger.error(f"  {self.name}: command not found — {e}")
            return False
        except Exception as e:
            logger.error(f"  {self.name}: failed to start — {e}")
            return False

    def stop(self) -> None:
        """Stop the subprocess gracefully."""
        if self.process and self.process.poll() is None:
            logger.info(f"  {self.name}: stopping (PID {self.process.pid})...")
            try:
                self.process.terminate()
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning(f"  {self.name}: force killing...")
                self.process.kill()
                self.process.wait()

        # Clean up PID file
        if self.pid_file.exists():
            self.pid_file.unlink()

        logger.info(f"  {self.name}: stopped")

    def is_running(self) -> bool:
        """Check if the subprocess is still alive."""
        if self.process is None:
            return False
        return self.process.poll() is None

    def check_and_restart(self) -> None:
        """Restart the process if it has crashed."""
        if self.is_running():
            return

        if self.process is not None:
            # Process existed but died
            exit_code = self.process.returncode
            self.restart_count += 1

            if self.restart_count > self.max_restarts:
                logger.error(
                    f"  {self.name}: crashed {self.restart_count} times — "
                    f"giving up (last exit code: {exit_code})"
                )
                return

            logger.warning(
                f"  {self.name}: crashed (exit code {exit_code}), "
                f"restarting in {RESTART_DELAY}s "
                f"(attempt {self.restart_count}/{self.max_restarts})"
            )
            time.sleep(RESTART_DELAY)
            self.start()

    def get_recent_output(self, lines: int = 5) -> list[str]:
        """Read recent output from the process."""
        if self.process and self.process.stdout:
            output = []
            try:
                # Non-blocking read
                while len(output) < lines:
                    line = self.process.stdout.readline()
                    if not line:
                        break
                    output.append(line.strip())
            except Exception:
                pass
            return output
        return []


# ---------------------------------------------------------------------------
# Approval Folder Watcher
# ---------------------------------------------------------------------------

class ApprovalFolderWatcher:
    """Monitors vault/approved/ for files moved there by the user.

    When a task file appears in vault/approved/, this watcher:
    1. Updates its frontmatter to status: approved
    2. Moves it to vault/tasks/ for the orchestrator to pick up
    3. Writes a trigger file
    """

    def __init__(self) -> None:
        self._known_files: set[str] = set()
        for f in APPROVED_DIR.glob("*.md"):
            self._known_files.add(f.name)

    def check(self) -> None:
        """Poll the approved folder for new files."""
        for md_file in APPROVED_DIR.glob("*.md"):
            if md_file.name in self._known_files:
                continue
            if md_file.name.startswith("_"):
                continue

            self._known_files.add(md_file.name)
            logger.info(f"  Approved file detected: {md_file.name}")
            self._process_approved(md_file)

    def _process_approved(self, file_path: Path) -> None:
        """Move an approved file to vault/tasks/ with status: approved."""
        try:
            # Import parser
            sys.path.insert(0, str(PROJECT_ROOT))
            from watchers.utils.markdown_parser import update_frontmatter

            # Update status to approved
            update_frontmatter(file_path, {"status": "approved"})

            # Move to tasks directory
            dest = TASKS_DIR / file_path.name
            shutil.move(str(file_path), str(dest))

            # Write trigger for orchestrator
            trigger = TASKS_DIR / ".trigger"
            trigger.write_text(file_path.stem, encoding="utf-8")

            logger.info(f"  Task approved and moved to: {dest.name}")

        except Exception as e:
            logger.error(f"  Failed to process approved file: {e}")


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

class Supervisor:
    """Main supervisor that manages all AI Employee components."""

    def __init__(self) -> None:
        python_cmd = sys.executable  # Use same Python that launched us

        self.processes = [
            ManagedProcess(
                name="file-watcher",
                command=[python_cmd, "-m", "watchers.file_watcher"],
                cwd=PROJECT_ROOT,
            ),
            ManagedProcess(
                name="orchestrator",
                command=[python_cmd, "-m", "orchestrator.run"],
                cwd=PROJECT_ROOT,
            ),
        ]

        self.approval_watcher = ApprovalFolderWatcher()
        self._running = True

    def start_all(self) -> None:
        """Start all managed processes."""
        print(BANNER)
        logger.info("Starting AI Employee system...")
        logger.info(f"  Project root: {PROJECT_ROOT}")
        logger.info(f"  Vault:        {VAULT_ROOT}")
        logger.info(f"  Python:       {sys.executable}")
        logger.info(f"  Platform:     {platform.system()} {platform.release()}")
        logger.info("")

        # Ensure all directories exist
        for d in (INBOX_DIR, NEEDS_ACTION_DIR, APPROVED_DIR,
                  COMPLETED_DIR, TASKS_DIR, TASKS_DIR / "archive",
                  LOG_DIR, PID_DIR):
            d.mkdir(parents=True, exist_ok=True)

        logger.info("Starting components:")
        for proc in self.processes:
            proc.start()

        logger.info("")
        logger.info("All systems online. Monitoring...")
        logger.info("  Press Ctrl+C to stop.")
        logger.info("")

        # Log startup event
        self._log_event("system-started", "All components launched")

    def stop_all(self) -> None:
        """Stop all managed processes."""
        logger.info("")
        logger.info("Stopping all components:")
        for proc in reversed(self.processes):
            proc.stop()

        self._log_event("system-stopped", "All components shut down")
        logger.info("All systems stopped.")

    def run(self) -> None:
        """Main supervisor loop — monitors health and approvals."""
        self.start_all()

        # Handle Ctrl+C
        def signal_handler(sig, frame):
            self._running = False

        signal.signal(signal.SIGINT, signal_handler)

        try:
            while self._running:
                # Check kill switch
                if HALT_FILE.exists():
                    logger.warning("HALT.md detected — pausing all systems")
                    self._log_event("system-halted", "HALT.md kill switch activated")

                    while HALT_FILE.exists() and self._running:
                        time.sleep(2)

                    if self._running:
                        logger.info("HALT.md removed — resuming")
                        self._log_event("system-resumed", "HALT.md removed")

                # Check process health
                for proc in self.processes:
                    proc.check_and_restart()

                # Check for folder-based approvals
                self.approval_watcher.check()

                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            pass

        self.stop_all()

    def status(self) -> None:
        """Print the status of all components."""
        logger.info("Component Status:")
        for proc in self.processes:
            if proc.pid_file.exists():
                pid = proc.pid_file.read_text(encoding="utf-8").strip()
                logger.info(f"  {proc.name}: PID {pid} (check manually)")
            else:
                logger.info(f"  {proc.name}: not running")

    def _log_event(self, action: str, message: str) -> None:
        """Write a supervisor event to the vault logs."""
        try:
            sys.path.insert(0, str(PROJECT_ROOT))
            from orchestrator.logger import audit
            audit.log_system(f"watchdog:{action} — {message}")
        except Exception:
            pass  # Don't crash the supervisor over logging


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def kill_existing() -> None:
    """Stop any running processes based on PID files."""
    if not PID_DIR.exists():
        logger.info("No running processes found.")
        return

    for pid_file in PID_DIR.glob("*.pid"):
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            name = pid_file.stem
            logger.info(f"  Stopping {name} (PID {pid})...")

            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)

            pid_file.unlink()
            logger.info(f"  {name}: stopped")

        except (ProcessLookupError, ValueError):
            pid_file.unlink()
            logger.info(f"  {pid_file.stem}: already stopped (stale PID)")

        except Exception as e:
            logger.error(f"  {pid_file.stem}: failed to stop — {e}")


def main() -> None:
    """CLI entry point for the watchdog supervisor."""
    parser = argparse.ArgumentParser(
        description="AI Employee Watchdog Supervisor"
    )
    parser.add_argument(
        "--stop", action="store_true",
        help="Stop all running components"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Check component status"
    )
    args = parser.parse_args()

    if args.stop:
        kill_existing()
    elif args.status:
        Supervisor().status()
    else:
        supervisor = Supervisor()
        supervisor.run()


if __name__ == "__main__":
    main()
