#!/usr/bin/env bash
# ============================================================================
# run_system.sh — Start the AI Employee system
#
# Launches all components and provides a live interactive interface.
#
# Usage:
#   bash run_system.sh              # Start everything
#   bash run_system.sh --stop       # Stop all components
#   bash run_system.sh --status     # Check component status
#   bash run_system.sh --demo       # Start + auto-trigger demo task
#   bash run_system.sh --test       # Run a quick test cycle
#
# Cross-platform: Works on Linux, macOS, and Windows (Git Bash / WSL)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Find Python — handle Windows Store alias issue
if python3 --version &>/dev/null 2>&1; then
    PYTHON=python3
elif python --version &>/dev/null 2>&1; then
    PYTHON=python
elif py --version &>/dev/null 2>&1; then
    PYTHON=py
else
    echo "ERROR: Python not found. Install Python 3.11+ and try again."
    exit 1
fi

# ---------------------------------------------------------------------------
# Stop mode
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--stop" ]]; then
    echo ""
    echo "Stopping AI Employee system..."
    $PYTHON -m supervisor.watchdog --stop 2>/dev/null || true

    # Also kill by PID files
    if [ -d ".pids" ]; then
        for pidfile in .pids/*.pid; do
            if [ -f "$pidfile" ]; then
                pid=$(cat "$pidfile")
                name=$(basename "$pidfile" .pid)
                echo "  Stopping $name (PID $pid)..."
                kill "$pid" 2>/dev/null || true
                rm -f "$pidfile"
            fi
        done
    fi
    echo "All components stopped."
    exit 0
fi

# ---------------------------------------------------------------------------
# Status mode
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--status" ]]; then
    echo ""
    echo "AI Employee System Status"
    echo "========================="

    if [ -d ".pids" ]; then
        for pidfile in .pids/*.pid; do
            if [ -f "$pidfile" ]; then
                pid=$(cat "$pidfile")
                name=$(basename "$pidfile" .pid)
                if kill -0 "$pid" 2>/dev/null; then
                    echo "  $name: RUNNING (PID $pid)"
                else
                    echo "  $name: STOPPED (stale PID $pid)"
                    rm -f "$pidfile"
                fi
            fi
        done
    else
        echo "  No components running."
    fi

    echo ""
    echo "Vault Status:"
    echo "  Inbox:        $(ls vault/inbox/*.md 2>/dev/null | grep -cv '^vault/inbox/_' || echo 0) task(s)"
    echo "  Needs Action: $(ls vault/needs_action/*.md 2>/dev/null | wc -l || echo 0) task(s)"
    echo "  Approved:     $(ls vault/approved/*.md 2>/dev/null | wc -l || echo 0) task(s)"
    echo "  Completed:    $(ls vault/completed/*.md 2>/dev/null | wc -l || echo 0) task(s)"
    echo "  Logs:         $(ls vault/logs/2026-*.md 2>/dev/null | wc -l || echo 0) entries"
    echo ""
    exit 0
fi

# ---------------------------------------------------------------------------
# Test mode
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--test" ]]; then
    echo ""
    echo "Running quick integration test..."
    echo ""

    # Clean state
    rm -f vault/tasks/*.md vault/tasks/.trigger vault/tasks/archive/*.md
    rm -f vault/needs_action/*.md vault/approved/*.md vault/completed/*.md
    rm -f vault/logs/2026-*.md vault/drafts/*.md

    $PYTHON -c "
import shutil
from pathlib import Path
from watchers.utils.markdown_parser import update_frontmatter, parse_frontmatter
from orchestrator.task_manager import TaskManager, TaskStatus
from orchestrator.claude_bridge import generate_plan
from orchestrator.action_dispatcher import ActionDispatcher, format_results_markdown
from orchestrator.dashboard import DashboardUpdater
from orchestrator.logger import audit

# Simulate watcher
inbox = Path('vault/inbox/_demo-task.md')
dest = Path('vault/tasks/test-task.md')
shutil.copy2(str(inbox), str(dest))
update_frontmatter(dest, {'status': 'pending', 'id': 'test-001'})

# Run orchestrator pipeline
tm = TaskManager(); d = ActionDispatcher(); dash = DashboardUpdater()
task = tm.get_pending_tasks()[0]
tm.transition(task, TaskStatus.PLANNING)
plan = generate_plan(task.body)
tm.write_plan(task, plan)
tm.transition(task, TaskStatus.AWAITING_APPROVAL)
update_frontmatter(task.file_path, {'status': 'approved'})
task.status = TaskStatus.APPROVED
tm.transition(task, TaskStatus.EXECUTING)
results = d.execute_steps(d.parse_plan_steps(task.body))
tm.write_result(task, format_results_markdown(results))
tm.transition(task, TaskStatus.COMPLETED)
tm.archive_task(task)
dash.update(orchestrator_status='Running')

# Verify
fm, body = parse_frontmatter(task.file_path)
assert fm['status'] == 'completed', f'Bad status: {fm[\"status\"]}'
assert '## Proposed Plan' in body
assert '## Execution Result' in body
logs = list(Path('vault/logs').glob('2026-*.md'))
assert len(logs) > 0

print('')
print('  [OK] Task lifecycle: pending -> completed')
print('  [OK] Plan generated and written')
print('  [OK] Execution results recorded')
print(f'  [OK] Audit logs: {len(logs)} entries')
print('')
print('  INTEGRATION TEST: PASSED')
"
    echo ""
    exit 0
fi

# ---------------------------------------------------------------------------
# Demo mode
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--demo" ]]; then
    echo ""
    echo "Starting demo mode..."
    echo ""

    # Clean previous demo artifacts
    rm -f vault/tasks/*.md vault/tasks/.trigger vault/tasks/archive/*.md
    rm -f vault/needs_action/*.md vault/approved/*.md vault/completed/*.md
    rm -f vault/logs/2026-*.md vault/drafts/*.md

    # Start orchestrator in background
    echo "Starting orchestrator..."
    $PYTHON -m orchestrator.orchestrator &
    ORCH_PID=$!
    mkdir -p .pids
    echo "$ORCH_PID" > .pids/orchestrator.pid
    sleep 2

    # Drop demo task
    echo ""
    echo "Dropping demo task into inbox..."
    TASK_FILE="vault/inbox/2026-02-12_demo-weekly-report.md"
    cp vault/inbox/_demo-task.md "$TASK_FILE"

    # Simulate watcher processing
    $PYTHON -c "
from pathlib import Path
import shutil
from watchers.utils.markdown_parser import update_frontmatter
src = Path('$TASK_FILE')
if src.exists():
    update_frontmatter(src, {'status': 'pending'})
    dest = Path('vault/tasks') / src.name
    shutil.move(str(src), str(dest))
    Path('vault/tasks/.trigger').write_text('task-20260212-demo')
    print('  Task moved to vault/tasks/')
"

    echo ""
    echo "  The orchestrator is now planning the task."
    echo "  Wait a few seconds, then approve:"
    echo ""
    echo "    Option A: Move vault/needs_action/*.md to vault/approved/"
    echo "    Option B: Edit vault/tasks/*.md → status: approved"
    echo ""
    echo "  Press Ctrl+C to stop the orchestrator."
    echo ""

    # Wait for orchestrator
    wait $ORCH_PID 2>/dev/null || true
    exit 0
fi

# ---------------------------------------------------------------------------
# Normal start mode
# ---------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          PERSONAL AI EMPLOYEE — STARTING SYSTEM             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Starting the watchdog supervisor..."
echo "This will manage the file watcher and orchestrator."
echo ""
echo "  To trigger a task:  Drop a .md file into vault/inbox/"
echo "  To approve:         Move from vault/needs_action/ to vault/approved/"
echo "  To stop:            Press Ctrl+C  (or: bash run_system.sh --stop)"
echo "  Kill switch:        Create vault/HALT.md"
echo ""

# Start the watchdog supervisor (manages everything)
$PYTHON -m supervisor.watchdog
