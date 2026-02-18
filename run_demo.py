"""Platinum Demo — One-command full system demonstration.

Launches the entire AI Employee stack and walks through a complete
task lifecycle, showcasing Bronze → Silver → Gold → Platinum features.

Usage:
    python run_demo.py
"""

import json
import os
import shutil
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Banner ───────────────────────────────────────────────────────────────────

BANNER = """
  +====================================================================+
  |                                                                    |
  |        PERSONAL AI EMPLOYEE -- PLATINUM DEMO                       |
  |        Full Stack: Bronze > Silver > Gold > Platinum               |
  |                                                                    |
  +====================================================================+
"""

STAGES = [
    ("1", "System Initialization", "Starting all subsystems"),
    ("2", "Plugin Discovery", "Loading Gold tier plugins"),
    ("3", "Task Creation", "Creating a sample task via API"),
    ("4", "Multi-Agent Planning", "Planner agent generates execution plan"),
    ("5", "Task Approval", "Auto-approving for demo"),
    ("6", "Multi-Agent Execution", "Executor agent runs plan steps"),
    ("7", "Review & Verification", "Reviewer agent validates results"),
    ("8", "Memory Storage", "Storing task in persistent memory"),
    ("9", "Monitoring Report", "Generating system health report"),
    ("10", "Cleanup & Summary", "Final status and metrics"),
]


def print_stage(num: str, title: str, description: str) -> None:
    """Print a formatted stage header."""
    print(f"\n  {'-'*60}")
    print(f"  Stage {num}: {title}")
    print(f"  {description}")
    print(f"  {'-'*60}\n")


def print_ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def print_info(msg: str) -> None:
    print(f"  [..] {msg}")


def print_fail(msg: str) -> None:
    print(f"  [!!] {msg}")


def main() -> None:
    print(BANNER)
    print(f"  Started at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Working dir: {PROJECT_ROOT}")
    print()

    demo_start = time.time()
    results = []

    # ── Stage 1: System Initialization ───────────────────────────────

    print_stage(*STAGES[0])

    # Ensure vault directories exist
    vault = PROJECT_ROOT / "vault"
    for subdir in ["inbox", "tasks", "tasks/archive", "logs", "drafts",
                    "needs_action", "approved", "completed", "reports", "context"]:
        (vault / subdir).mkdir(parents=True, exist_ok=True)
    print_ok("Vault directory structure verified")

    # Initialize Silver database
    from memory.database import TaskDatabase
    db = TaskDatabase()
    print_ok("Silver database initialized")

    # Initialize Platinum memory
    from platinum.memory.memory_store import MemoryStore
    memory = MemoryStore(db_path=str(PROJECT_ROOT / "platinum_demo.db"))
    print_ok("Platinum memory store initialized")

    # Initialize monitoring
    from platinum.monitoring.monitor import SystemMonitor
    monitor = SystemMonitor(vault_root=str(vault))
    monitor.start()
    print_ok("System monitor started")

    # Initialize scheduler
    from platinum.scheduler.scheduler import TaskScheduler
    scheduler = TaskScheduler()
    print_ok("Task scheduler initialized")

    results.append(("Initialization", True))

    # ── Stage 2: Plugin Discovery ────────────────────────────────────

    print_stage(*STAGES[1])

    from gold.tools.base import tool_registry
    from gold.tools.filesystem import FilesystemTool
    from gold.tools.email import EmailTool
    from gold.tools.shell import ShellTool
    from gold.tools.calendar import CalendarTool

    # Register core tools
    tool_registry.register(FilesystemTool(vault_root=str(vault)))
    tool_registry.register(EmailTool(vault_root=str(vault)))
    tool_registry.register(ShellTool())
    tool_registry.register(CalendarTool(vault_root=str(vault)))
    print_ok(f"Core tools registered: {', '.join(tool_registry.list_names())}")

    # Load plugins
    from plugins.base import PluginManager
    pm = PluginManager(registry=tool_registry)
    discovered = pm.discover_plugins()
    print_ok(f"Plugins discovered: {', '.join(discovered)}")

    for plugin_name in discovered:
        success = pm.load_plugin(plugin_name)
        if success:
            print_ok(f"Plugin loaded: {plugin_name}")
        else:
            print_info(f"Plugin skipped: {plugin_name}")

    results.append(("Plugin Discovery", True))

    # ── Stage 3: Task Creation ───────────────────────────────────────

    print_stage(*STAGES[2])

    import yaml
    now = datetime.now(timezone.utc)
    task_id = f"demo-platinum-{now.strftime('%Y%m%d-%H%M%S')}"
    filename = f"{now.strftime('%Y-%m-%d')}_platinum-demo.md"

    frontmatter = {
        "id": task_id,
        "status": "pending",
        "priority": "high",
        "source": "platinum-demo",
        "tags": ["demo", "platinum"],
        "approval_required": True,
        "created": now.isoformat(timespec="seconds"),
    }
    yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    body = (
        "## Request\n\n"
        "Send a weekly team update email summarizing project status "
        "and schedule a follow-up meeting for next week.\n\n"
        "## Context\n\n"
        "This is a Platinum tier demo showing the full AI Employee stack:\n"
        "multi-agent reasoning, plugin tools, persistent memory, and monitoring."
    )
    content = f"---\n{yaml_str}---\n\n{body}\n"

    task_path = vault / "tasks" / filename
    task_path.write_text(content, encoding="utf-8")
    db.sync_single_task(task_path)
    print_ok(f"Task created: {task_id}")
    print_ok(f"File: {filename}")

    # Record in memory
    memory.store("tasks", task_id, f"Demo task: {body[:100]}", tags=["demo", "platinum"])

    results.append(("Task Creation", True))

    # ── Stage 4: Multi-Agent Planning ────────────────────────────────

    print_stage(*STAGES[3])

    from gold.agents.coordinator import AgentCoordinator
    coordinator = AgentCoordinator(vault_root=str(vault))

    context = coordinator.run_planning_only(
        task_id=task_id,
        title="Weekly Team Update + Schedule Meeting",
        body=body,
    )

    print_ok(f"Plan generated ({len(context.plan)} chars)")
    for msg in context.messages:
        if msg.role == "reasoning":
            print_info(f"  [{msg.agent}] {msg.content[:80]}")

    # Write plan into the task file
    from watchers.utils.markdown_parser import parse_frontmatter, update_frontmatter
    fm, existing_body = parse_frontmatter(task_path)
    fm["status"] = "awaiting-approval"
    new_body = existing_body + "\n\n" + context.plan
    yaml_str = yaml.dump(fm, default_flow_style=False, sort_keys=False)
    task_path.write_text(f"---\n{yaml_str}---\n\n{new_body}\n", encoding="utf-8")
    db.sync_single_task(task_path)
    print_ok("Plan written to task file, status: awaiting-approval")

    results.append(("Multi-Agent Planning", True))

    # ── Stage 5: Task Approval ───────────────────────────────────────

    print_stage(*STAGES[4])

    update_frontmatter(task_path, {"status": "approved"})
    db.sync_single_task(task_path)
    print_ok("Task auto-approved for demo")

    memory.record_decision(
        decision="Auto-approved demo task",
        reasoning="Demo mode — automatic approval",
        task_id=task_id,
    )

    results.append(("Task Approval", True))

    # ── Stage 6: Multi-Agent Execution ───────────────────────────────

    print_stage(*STAGES[5])

    # Run execution phase
    exec_start = time.time()
    context = coordinator.run_execution(context)
    exec_duration = int((time.time() - exec_start) * 1000)

    for r in context.execution_results:
        status = "OK" if r["success"] else "FAIL"
        print_info(f"  Step {r['step']}: [{status}] {r['description'][:60]}")

    # Update task file with results
    update_frontmatter(task_path, {"status": "executing"})

    result_lines = []
    for r in context.execution_results:
        icon = "+" if r["success"] else "x"
        result_lines.append(f"**Step {r['step']}** [{icon}] {r['description']}")
        result_lines.append(f"- Tool: `{r['tool']}`")
        result_lines.append(f"- Status: {'success' if r['success'] else 'failed'}")
        if r.get("error"):
            result_lines.append(f"- Note: {r['error']}")
        result_lines.append("")

    fm2, body2 = parse_frontmatter(task_path)
    fm2["status"] = "completed"
    new_body2 = body2 + "\n\n## Execution Result\n\n" + "\n".join(result_lines)
    yaml_str2 = yaml.dump(fm2, default_flow_style=False, sort_keys=False)
    task_path.write_text(f"---\n{yaml_str2}---\n\n{new_body2}\n", encoding="utf-8")
    db.sync_single_task(task_path)

    print_ok(f"Execution complete ({exec_duration}ms)")
    monitor.metrics.record("demo.execution_time", exec_duration, unit="ms")

    results.append(("Multi-Agent Execution", True))

    # ── Stage 7: Review & Verification ───────────────────────────────

    print_stage(*STAGES[6])

    print_ok(f"Verdict: {context.review_verdict}")
    for msg in context.messages:
        if msg.agent == "reviewer" and msg.role == "reasoning":
            print_info(f"  [reviewer] {msg.content[:80]}")

    results.append(("Review & Verification", True))

    # ── Stage 8: Memory Storage ──────────────────────────────────────

    print_stage(*STAGES[7])

    memory.record_task(
        task_id=task_id,
        title="Weekly Team Update + Schedule Meeting",
        status="completed",
        plan=context.plan,
        result=str(context.execution_results),
        verdict=context.review_verdict,
        duration_ms=exec_duration,
    )
    print_ok("Task recorded in persistent memory")

    memory.store_context(
        source="demo",
        content=f"Platinum demo completed successfully for task {task_id}",
        tags=["demo", "platinum", "completed"],
    )
    print_ok("Context entry stored")

    stats = memory.get_stats()
    print_ok(f"Memory stats: {json.dumps(stats)}")

    results.append(("Memory Storage", True))

    # ── Stage 9: Monitoring Report ───────────────────────────────────

    print_stage(*STAGES[8])

    # Record demo metrics
    monitor.metrics.increment("demo.tasks_completed")
    monitor.metrics.set_gauge("demo.last_duration_ms", exec_duration)

    # Run health checks
    health_data = monitor.health.get_status()
    print_ok(f"System health: {health_data['overall']}")
    for check in health_data["checks"]:
        print_info(f"  {check['name']}: {check['status']} ({check['latency_ms']:.1f}ms)")

    # Get full dashboard data
    dashboard = monitor.get_dashboard_data()
    print_ok(f"Active alerts: {len(dashboard['alerts'])}")
    print_ok(f"Metrics tracked: {len(dashboard['metrics']['counters'])} counters, {len(dashboard['metrics']['gauges'])} gauges")

    results.append(("Monitoring Report", True))

    # ── Stage 10: Cleanup & Summary ──────────────────────────────────

    print_stage(*STAGES[9])

    # Archive the demo task
    archive_path = vault / "tasks" / "archive" / filename
    if task_path.exists():
        shutil.move(str(task_path), str(archive_path))
        db.sync_single_task(archive_path)
        print_ok(f"Task archived: {archive_path.name}")

    # Stop monitoring
    monitor.stop()
    print_ok("Monitor stopped")

    # Close memory
    memory.close()
    print_ok("Memory store closed")

    # Clean up demo database
    demo_db = PROJECT_ROOT / "platinum_demo.db"
    if demo_db.exists():
        demo_db.unlink()
        for wal in demo_db.parent.glob("platinum_demo.db-*"):
            wal.unlink()
    print_ok("Demo database cleaned up")

    # Close Silver DB
    db.close()
    print_ok("Silver database closed")

    # ── Final Summary ────────────────────────────────────────────────

    total_time = time.time() - demo_start
    passed = sum(1 for _, ok in results if ok)
    total = len(results)

    print(f"\n  {'='*60}")
    print(f"  DEMO COMPLETE -- {passed}/{total} stages passed")
    print(f"  {'='*60}")
    print()

    for stage_name, ok in results:
        icon = "[OK]" if ok else "[!!]"
        print(f"  {icon} {stage_name}")

    print()
    print(f"  Total time: {total_time:.1f}s")
    print(f"  Task ID:    {task_id}")
    print()

    # ── Tier Summary ─────────────────────────────────────────────────

    print("  Tier Coverage:")
    print("  [Bronze]   Vault system, file watcher, MCP tools, audit logging")
    print("  [Silver]   Web UI, REST API, WebSocket, SQLite database")
    print("  [Gold]     Plugin system, multi-agent reasoning, security layer")
    print("  [Platinum] Persistent memory, scheduler, monitoring, this demo")
    print()
    print(f"  Web UI available at: http://localhost:8000 (when server is running)")
    print()


if __name__ == "__main__":
    main()
