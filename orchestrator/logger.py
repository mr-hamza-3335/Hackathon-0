"""Audit logger — writes structured log entries to vault/logs/.

Every orchestrator action produces a markdown log file with YAML frontmatter
and a human-readable body. Logs are append-only: never overwrite, never delete.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from orchestrator.config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
console = logging.getLogger("orchestrator")


class AuditLogger:
    """Writes structured audit logs to the vault."""

    def __init__(self, logs_dir: Path | None = None) -> None:
        self.logs_dir = logs_dir or config.vault.logs
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._action_counter = 0

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _make_filename(self, action: str) -> str:
        now = datetime.now(timezone.utc)
        slug = (
            action.replace(" ", "-").replace("_", "-")
            .replace(":", "-").replace("/", "-").replace("\\", "-")
            .replace(">", "").replace("<", "").replace('"', "")
            .replace("|", "").replace("?", "").replace("*", "")
            .lower()[:30]
        )
        # Add counter to guarantee uniqueness within the same second
        self._action_counter += 1
        return now.strftime(f"%Y-%m-%d_%H-%M-%S_{self._action_counter:03d}_{slug}.md")

    def log_action(
        self,
        task_id: str,
        action: str,
        tool: str = "none",
        input_summary: str = "",
        output_summary: str = "",
        status: str = "success",
        error: str = "",
        duration_ms: int = 0,
        extra: dict[str, Any] | None = None,
    ) -> Path:
        """Write a single audit log entry to vault/logs/."""
        timestamp = self._timestamp()

        frontmatter: dict[str, Any] = {
            "timestamp": timestamp,
            "task_id": task_id,
            "action": action,
            "tool": tool,
            "status": status,
            "duration_ms": duration_ms,
        }
        if error:
            frontmatter["error"] = error

        yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)

        body_lines = [
            "## Action Log",
            "",
            f"**Action**: {action}",
            f"**Tool**: {tool}",
            f"**Input**: {input_summary}",
            f"**Output**: {output_summary}",
            f"**Status**: {status}",
            f"**Duration**: {duration_ms}ms",
        ]
        if error:
            body_lines.append(f"**Error**: {error}")
        if extra:
            body_lines.append("")
            body_lines.append("### Details")
            body_lines.append(f"```json\n{json.dumps(extra, indent=2)}\n```")

        content = f"---\n{yaml_str}---\n\n" + "\n".join(body_lines) + "\n"

        filename = self._make_filename(action)
        filepath = self.logs_dir / filename
        filepath.write_text(content, encoding="utf-8")

        icon = "+" if status == "success" else "x"
        console.info(f"[{icon}] {action} ({tool}) -> {status}")

        return filepath

    def log_lifecycle(self, task_id: str, old_status: str, new_status: str) -> Path:
        """Log a task lifecycle state transition."""
        return self.log_action(
            task_id=task_id,
            action=f"status-change:{old_status}->{new_status}",
            tool="task_manager",
            input_summary=f"Transition from {old_status} to {new_status}",
            output_summary=f"Task is now {new_status}",
            status="success",
        )

    def log_error(self, task_id: str, action: str, error: str) -> Path:
        """Log an error event."""
        console.error(f"[!] {action}: {error}")
        return self.log_action(
            task_id=task_id,
            action=action,
            status="failure",
            error=error,
        )

    def log_system(self, message: str) -> Path:
        """Log a system-level event (startup, shutdown, halt)."""
        console.info(f"[*] {message}")
        return self.log_action(
            task_id="system",
            action=message,
            tool="orchestrator",
            status="success",
        )


# Singleton
audit = AuditLogger()
