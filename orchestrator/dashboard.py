"""Dashboard updater — keeps vault/dashboard.md in sync with system state.

Rewrites the dashboard file with current status, pending approvals,
active tasks, and recent log entries.
"""

from datetime import datetime, timezone
from pathlib import Path

import yaml

from orchestrator.config import config
from watchers.utils.markdown_parser import parse_frontmatter


class DashboardUpdater:
    """Maintains the live dashboard in the Obsidian vault."""

    def __init__(self) -> None:
        self.dashboard_path = config.vault.root / "dashboard.md"
        self.tasks_dir = config.vault.tasks
        self.logs_dir = config.vault.logs

    def update(
        self,
        watcher_status: str = "Unknown",
        orchestrator_status: str = "Running",
        mcp_status: str = "Standby",
    ) -> None:
        """Rewrite dashboard.md with current system state."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # Gather task info
        pending_approvals: list[dict] = []
        active_tasks: list[dict] = []

        for md_file in sorted(self.tasks_dir.glob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                fm, _ = parse_frontmatter(md_file)
                status = fm.get("status", "")
                task_id = fm.get("id", md_file.stem)
                priority = fm.get("priority", "medium")

                if status == "awaiting-approval":
                    pending_approvals.append({
                        "id": task_id,
                        "file": md_file.name,
                        "priority": priority,
                    })
                elif status in ("pending", "planning", "executing"):
                    active_tasks.append({
                        "id": task_id,
                        "file": md_file.name,
                        "status": status,
                    })
            except Exception:
                continue

        # Gather recent logs (last 5)
        recent_logs: list[dict] = []
        log_files = sorted(self.logs_dir.glob("*.md"), reverse=True)
        for log_file in log_files[:5]:
            if log_file.name.startswith("_"):
                continue
            try:
                fm, _ = parse_frontmatter(log_file)
                recent_logs.append({
                    "time": fm.get("timestamp", "")[:19],
                    "task": fm.get("task_id", ""),
                    "action": fm.get("action", ""),
                    "status": fm.get("status", ""),
                })
            except Exception:
                continue

        # Build dashboard content
        lines = [
            "---",
            "title: AI Employee Dashboard",
            f"updated: \"{now}\"",
            "---",
            "",
            "# AI Employee Dashboard",
            "",
            "## System Status",
            "",
            "| Component | Status |",
            "|---|---|",
            f"| File Watcher | {watcher_status} |",
            f"| Orchestrator | {orchestrator_status} |",
            f"| MCP Servers | {mcp_status} |",
            "",
        ]

        # Pending approvals
        lines.append("## Pending Approvals")
        lines.append("")
        if pending_approvals:
            for pa in pending_approvals:
                lines.append(
                    f"- **{pa['id']}** ({pa['priority']}) — "
                    f"[[{pa['file']}]] — Edit status to `approved`"
                )
        else:
            lines.append("_No pending approvals._")
        lines.append("")

        # Recent actions
        lines.append("## Recent Actions")
        lines.append("")
        lines.append("| Time | Task | Action | Status |")
        lines.append("|---|---|---|---|")
        if recent_logs:
            for log in recent_logs:
                lines.append(
                    f"| {log['time']} | {log['task']} | {log['action']} | {log['status']} |"
                )
        else:
            lines.append("| — | — | — | — |")
        lines.append("")

        # Active tasks
        lines.append("## Active Tasks")
        lines.append("")
        if active_tasks:
            for at in active_tasks:
                lines.append(
                    f"- **{at['id']}** — {at['status']} — [[{at['file']}]]"
                )
        else:
            lines.append("_No active tasks._")
        lines.append("")

        # Footer
        lines.append("---")
        lines.append("")
        lines.append(
            "> **Kill Switch**: Create `HALT.md` in this vault to "
            "immediately stop all automation."
        )
        lines.append("")

        self.dashboard_path.write_text("\n".join(lines), encoding="utf-8")
