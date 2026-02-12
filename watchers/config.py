"""Watcher configuration loader."""

from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

VAULT_ROOT = Path(os.getenv("VAULT_ROOT", "./vault"))
INBOX_PATH = VAULT_ROOT / "inbox"
TASKS_PATH = VAULT_ROOT / "tasks"
POLL_INTERVAL = int(os.getenv("WATCHER_POLL_INTERVAL", "3"))
