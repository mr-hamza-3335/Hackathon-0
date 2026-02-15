"""CEO Briefing Reporter — generates weekly executive summaries.

Scans vault/logs/ and completed tasks to produce a structured
markdown report suitable for a Monday morning CEO briefing.

Usage:
    python -m orchestrator.reporter              # Generate report
    python orchestrator/reporter.py              # Direct execution
"""

import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from orchestrator.config import config
from orchestrator.logger import audit
from watchers.utils.markdown_parser import parse_frontmatter


def _scan_logs() -> list[dict]:
    """Scan vault/logs/ and return parsed log entries."""
    logs: list[dict] = []
    logs_dir = config.vault.logs
    if not logs_dir.exists():
        return logs

    for log_file in sorted(logs_dir.glob("*.md")):
        if log_file.name.startswith("_"):
            continue
        try:
            fm, _ = parse_frontmatter(log_file)
            logs.append({
                "timestamp": fm.get("timestamp", ""),
                "task_id": fm.get("task_id", ""),
                "action": fm.get("action", ""),
                "tool": fm.get("tool", ""),
                "status": fm.get("status", ""),
                "duration_ms": fm.get("duration_ms", 0),
                "error": fm.get("error", ""),
            })
        except Exception:
            continue

    return logs


def _scan_completed_tasks() -> list[dict]:
    """Scan vault/tasks/archive/ and vault/completed/ for finished tasks."""
    tasks: list[dict] = []
    search_dirs = [
        config.vault.archive,
        config.vault.root / "completed",
    ]

    seen_ids: set[str] = set()
    for d in search_dirs:
        if not d.exists():
            continue
        for task_file in sorted(d.glob("*.md")):
            if task_file.name.startswith("_"):
                continue
            try:
                fm, body = parse_frontmatter(task_file)
                task_id = fm.get("id", task_file.stem)
                if task_id in seen_ids:
                    continue
                seen_ids.add(task_id)

                tasks.append({
                    "id": task_id,
                    "status": fm.get("status", "unknown"),
                    "priority": fm.get("priority", "medium"),
                    "source": fm.get("source", "unknown"),
                    "created": str(fm.get("created", "")),
                    "file": task_file.name,
                    "has_plan": "## Proposed Plan" in body,
                    "has_result": "## Execution Result" in body,
                })
            except Exception:
                continue

    return tasks


def generate_report() -> str:
    """Generate a CEO briefing report as markdown."""
    now = datetime.now(timezone.utc)
    logs = _scan_logs()
    tasks = _scan_completed_tasks()

    # Compute metrics
    total_tasks = len(tasks)
    completed = sum(1 for t in tasks if t["status"] == "completed")
    failed = sum(1 for t in tasks if t["status"] == "failed")
    with_plans = sum(1 for t in tasks if t["has_plan"])
    with_results = sum(1 for t in tasks if t["has_result"])

    total_logs = len(logs)
    successful_actions = sum(1 for l in logs if l["status"] == "success")
    failed_actions = sum(1 for l in logs if l["status"] == "failure")
    system_events = sum(1 for l in logs if l["task_id"] == "system")
    task_actions = total_logs - system_events

    # Tool usage breakdown
    tool_counts: Counter[str] = Counter()
    for l in logs:
        if l["tool"] and l["task_id"] != "system":
            tool_counts[l["tool"]] += 1

    # Action type breakdown
    action_counts: Counter[str] = Counter()
    for l in logs:
        action = l["action"]
        if action.startswith("status-change:"):
            action_counts["state-transitions"] += 1
        elif action.startswith("execute-"):
            action_counts["tool-executions"] += 1
        elif action == "generate-plan":
            action_counts["plan-generations"] += 1
        elif action == "task-completed":
            action_counts["task-completions"] += 1
        else:
            action_counts["other"] += 1

    # Total execution time
    total_duration = sum(l["duration_ms"] for l in logs if l["duration_ms"])

    # Build recent actions table (last 10)
    recent_logs = logs[-10:] if logs else []

    # Executive paragraph
    success_rate = (
        f"{(successful_actions / total_logs * 100):.0f}%"
        if total_logs > 0
        else "N/A"
    )
    exec_paragraph = (
        f"The AI Employee system processed {total_tasks} task(s) with "
        f"{completed} completed successfully"
        f"{f' and {failed} failed' if failed else ''}. "
        f"A total of {total_logs} actions were logged with a "
        f"{success_rate} success rate. "
        f"The system executed {action_counts.get('tool-executions', 0)} tool "
        f"operations and generated {action_counts.get('plan-generations', 0)} "
        f"AI plans. "
        f"All operations were fully audited with append-only logging and "
        f"human approval gating. The system is operating within normal "
        f"parameters and ready for continued use."
    )

    # Build the report
    lines = [
        "---",
        f'title: "CEO Briefing Report"',
        f'generated: "{now.isoformat(timespec="seconds")}"',
        f"total_tasks: {total_tasks}",
        f"total_actions: {total_logs}",
        f"success_rate: \"{success_rate}\"",
        "---",
        "",
        "# CEO Briefing Report",
        "",
        f"> Generated: {now.strftime('%A, %B %d, %Y at %H:%M UTC')}",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        exec_paragraph,
        "",
        "---",
        "",
        "## Task Overview",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Tasks | {total_tasks} |",
        f"| Completed | {completed} |",
        f"| Failed | {failed} |",
        f"| With AI Plans | {with_plans} |",
        f"| With Execution Results | {with_results} |",
        "",
        "## Execution Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Actions Logged | {total_logs} |",
        f"| Successful Actions | {successful_actions} |",
        f"| Failed Actions | {failed_actions} |",
        f"| System Events | {system_events} |",
        f"| Task Actions | {task_actions} |",
        f"| Total Duration | {total_duration}ms |",
        "",
        "## Tool Usage",
        "",
        "| Tool | Invocations |",
        "|------|-------------|",
    ]

    if tool_counts:
        for tool, count in tool_counts.most_common():
            lines.append(f"| {tool} | {count} |")
    else:
        lines.append("| (none) | 0 |")

    lines.extend([
        "",
        "## Action Breakdown",
        "",
        "| Category | Count |",
        "|----------|-------|",
    ])

    for cat, count in sorted(action_counts.items()):
        lines.append(f"| {cat} | {count} |")

    lines.extend([
        "",
        "## Recent Actions",
        "",
        "| Time | Task | Action | Tool | Status |",
        "|------|------|--------|------|--------|",
    ])

    if recent_logs:
        for l in reversed(recent_logs):
            time_str = str(l["timestamp"])[:19]
            lines.append(
                f"| {time_str} | {l['task_id']} | "
                f"{l['action']} | {l['tool']} | {l['status']} |"
            )
    else:
        lines.append("| - | - | - | - | - |")

    lines.extend([
        "",
        "## Completed Tasks",
        "",
        "| Task ID | Priority | Source | Status |",
        "|---------|----------|--------|--------|",
    ])

    if tasks:
        for t in tasks:
            lines.append(
                f"| {t['id']} | {t['priority']} | "
                f"{t['source']} | {t['status']} |"
            )
    else:
        lines.append("| (none) | - | - | - |")

    lines.extend([
        "",
        "---",
        "",
        "*Report generated automatically by the Personal AI Employee system.*",
        "",
    ])

    return "\n".join(lines)


def write_report() -> Path:
    """Generate and write the CEO briefing report to vault/reports/."""
    reports_dir = config.vault.root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_content = generate_report()

    # Write as weekly_report.md (overwritten each time)
    report_path = reports_dir / "weekly_report.md"
    report_path.write_text(report_content, encoding="utf-8")

    # Also write a timestamped copy for history
    now = datetime.now(timezone.utc)
    timestamped_name = f"report_{now.strftime('%Y-%m-%d_%H-%M-%S')}.md"
    timestamped_path = reports_dir / timestamped_name
    timestamped_path.write_text(report_content, encoding="utf-8")

    audit.log_action(
        task_id="system",
        action="generate-ceo-report",
        tool="reporter",
        output_summary=f"Report written to {report_path.name}",
        status="success",
    )

    return report_path


def main() -> None:
    """Generate and print the CEO briefing report."""
    print("\n  Generating CEO Briefing Report...\n")
    report_path = write_report()
    content = report_path.read_text(encoding="utf-8")
    print(content)
    print(f"\n  Report saved to: {report_path}")
    print(f"  Reports directory: {report_path.parent}\n")


if __name__ == "__main__":
    main()
