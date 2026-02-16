"""File watcher — monitors vault/inbox/ for new task files."""

import logging
import shutil
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from watchers.config import INBOX_PATH, TASKS_PATH, POLL_INTERVAL
from watchers.utils.markdown_parser import parse_frontmatter, validate_frontmatter, update_frontmatter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [WATCHER] %(message)s")
logger = logging.getLogger(__name__)


class InboxHandler(FileSystemEventHandler):
    """Handle new files appearing in vault/inbox/."""

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        if file_path.suffix != ".md" or file_path.name.startswith("_"):
            return

        logger.info(f"New file detected: {file_path.name}")
        # Small delay to let the OS finish writing the file
        time.sleep(0.5)
        self._process_task(file_path)

    def _process_task(self, file_path: Path) -> None:
        """Validate and move a task file from inbox to tasks."""
        try:
            frontmatter, body = parse_frontmatter(file_path)

            missing = validate_frontmatter(frontmatter)
            if missing:
                logger.warning(f"Invalid task {file_path.name}: missing fields {missing}")
                return

            # Set status to pending
            update_frontmatter(file_path, {"status": "pending"})

            # Move to tasks directory
            dest = TASKS_PATH / file_path.name
            shutil.move(str(file_path), str(dest))
            logger.info(f"Task moved to: {dest.name}")

            # Write trigger file for orchestrator
            trigger = TASKS_PATH / ".trigger"
            trigger.write_text(frontmatter.get("id", file_path.stem), encoding="utf-8")
            logger.info(f"Trigger written for task: {frontmatter.get('id', 'unknown')}")

        except Exception:
            logger.exception(f"Error processing {file_path.name}")


def start_watcher() -> None:
    """Start watching the inbox directory."""
    INBOX_PATH.mkdir(parents=True, exist_ok=True)
    TASKS_PATH.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    observer.schedule(InboxHandler(), str(INBOX_PATH), recursive=False)
    observer.start()
    logger.info(f"Watching: {INBOX_PATH.resolve()}")

    try:
        while True:
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Shutting down watcher...")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    start_watcher()
