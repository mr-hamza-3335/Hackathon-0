# TASKS.md — Implementation Task Breakdown

> **Project:** Personal AI Employee — Bronze MVP
> **Last Updated:** 2026-02-12
> **Status Key:** DONE | IN-PROGRESS | TODO

---

## Phase 1: Setup

### Task 1.1: Project Scaffolding — DONE

**Description:** Create the full directory tree, config files, and `.gitignore` so every contributor starts from the same structure.

**Files to create:**
```
setup/init_project.sh
.env.example
.gitignore
requirements.txt
mcp-servers/demo-server/package.json
orchestrator/config.yaml
```

**Commands to run:**
```bash
chmod +x setup/init_project.sh
./setup/init_project.sh
```

**Expected output:**
```
=== Personal AI Employee — Project Scaffolding ===
[1/6] Creating directories...
[2/6] Creating vault templates...
[3/6] Creating Python source files...
[4/6] Creating prompt templates...
[5/6] Creating config files...
[6/6] Creating test stubs...
=== Scaffolding Complete ===
```

**Verification:**
```bash
# All 14 directories exist
find . -type d | wc -l  # >= 14
# Config files present
test -f .env.example && test -f .gitignore && test -f requirements.txt && echo "OK"
```

---

### Task 1.2: Python Environment — DONE

**Description:** Install Python dependencies for watchers and orchestrator.

**Files to create:** None (uses existing `requirements.txt`)

**Commands to run:**
```bash
pip install -r requirements.txt
```

**Expected output:**
```
Successfully installed watchdog-6.0.0 pyyaml-6.0.x python-dotenv-1.x.x
```

**Verification:**
```bash
python -c "import watchdog; import yaml; import dotenv; print('All deps OK')"
```

---

### Task 1.3: Node Environment — DONE

**Description:** Install Node dependencies for the MCP demo server.

**Files to create:** None (uses existing `package.json`)

**Commands to run:**
```bash
cd mcp-servers/demo-server && npm install
```

**Expected output:**
```
added 91 packages, and audited 92 packages
found 0 vulnerabilities
```

**Verification:**
```bash
node -e "import('@modelcontextprotocol/sdk/server/mcp.js').then(() => console.log('MCP SDK OK'))"
```

---

### Task 1.4: Environment Variables — DONE

**Description:** Create `.env` from template and configure API keys.

**Files to create:**
```
.env  (copy from .env.example, fill in values)
```

**Commands to run:**
```bash
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY
```

**Expected output:** `.env` file with valid `ANTHROPIC_API_KEY` set.

**Verification:**
```bash
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('Key set:', bool(os.getenv('ANTHROPIC_API_KEY')))"
```

---

### Task 1.5: Git Repository — TODO

**Description:** Initialize git repo, create initial commit with full scaffold.

**Files to create:**
```
.gitattributes  (enforce LF line endings)
```

**Commands to run:**
```bash
git init
echo "* text=auto eol=lf" > .gitattributes
git add -A
git commit -m "Initial scaffold: Bronze MVP project structure"
```

**Expected output:** Clean initial commit with all scaffold files.

**Verification:**
```bash
git log --oneline  # Shows 1 commit
git status          # Clean working tree
```

---

## Phase 2: Core System

### Task 2.1: Markdown Parser — DONE

**Description:** Build the frontmatter parser that reads/writes YAML metadata in task markdown files. This is the shared utility used by both watchers and the orchestrator.

**Files to create:**
```
watchers/utils/markdown_parser.py
```

**Commands to run:**
```bash
python -c "
from watchers.utils.markdown_parser import parse_frontmatter, validate_frontmatter
from pathlib import Path
# Test with the inbox template
fm, body = parse_frontmatter(Path('vault/inbox/_template.md'))
print(f'Parsed: {fm}')
print(f'Valid: {validate_frontmatter(fm)}')
"
```

**Expected output:**
```
Parsed: {'id': 'task-YYYYMMDD-NNN', 'status': 'new', ...}
Valid: []  (no missing fields)
```

**Verification:**
- `parse_frontmatter()` extracts YAML dict + body string
- `validate_frontmatter()` returns empty list for valid files
- `update_frontmatter()` modifies fields without corrupting body

---

### Task 2.2: Configuration Loader — DONE

**Description:** Build the config module that loads `config.yaml` with environment variable overrides and exposes typed dataclass objects.

**Files to create:**
```
orchestrator/config.py
orchestrator/config.yaml
```

**Commands to run:**
```bash
python -c "
from orchestrator.config import config
print(f'Vault root: {config.vault.root}')
print(f'Poll interval: {config.orchestrator.poll_interval_seconds}s')
print(f'Approval timeout: {config.approval.timeout_minutes}m')
"
```

**Expected output:**
```
Vault root: vault
Poll interval: 3s
Approval timeout: 60m
```

**Verification:**
- All 4 config dataclasses load without error
- `VAULT_ROOT` env var overrides yaml value
- Archive path is auto-derived from tasks path

---

### Task 2.3: Audit Logger — DONE

**Description:** Build the structured logging system that writes markdown audit log entries to `vault/logs/` with YAML frontmatter.

**Files to create:**
```
orchestrator/logger.py
```

**Commands to run:**
```bash
python -c "
from orchestrator.logger import audit
path = audit.log_action(task_id='test-001', action='test-log', tool='test', status='success')
print(f'Log written: {path}')
"
```

**Expected output:** Log file created at `vault/logs/YYYY-MM-DD_HH-MM-SS_NNN_test-log.md`

**Verification:**
- Log file has valid YAML frontmatter with timestamp, task_id, action, status
- Body contains human-readable summary
- Filenames are Windows-safe (no colons or special chars)
- Counter ensures uniqueness within the same second

---

### Task 2.4: Task Manager (State Machine) — DONE

**Description:** Build the task lifecycle engine with 9 states and enforced transitions. Reads/writes task files, appends plans and results, archives completed tasks.

**Files to create:**
```
orchestrator/task_manager.py
```

**Commands to run:**
```bash
python -c "
from orchestrator.task_manager import TaskManager, TaskStatus, TRANSITIONS
tm = TaskManager()
print(f'States: {[s.value for s in TaskStatus]}')
print(f'Transitions from pending: {[s.value for s in TRANSITIONS[TaskStatus.PENDING]]}')
"
```

**Expected output:**
```
States: ['new', 'pending', 'planning', 'awaiting-approval', 'approved', 'rejected', 'executing', 'completed', 'failed']
Transitions from pending: ['planning', 'failed']
```

**Verification:**
- `load_task()` parses a markdown file into a Task dataclass
- `transition()` enforces valid state changes, raises ValueError on invalid
- `write_plan()` appends `## Proposed Plan` to task file
- `write_result()` appends `## Execution Result` to task file
- `archive_task()` moves file to `vault/tasks/archive/`
- `check_trigger()` consumes and deletes `.trigger` file
- `get_pending_tasks()` finds all `status: pending` files

---

### Task 2.5: Approval Gate — DONE

**Description:** Build the human-in-the-loop approval system that polls task frontmatter until the user sets `status: approved` or `status: rejected` in Obsidian.

**Files to create:**
```
orchestrator/approval_gate.py
```

**Commands to run:**
```bash
python -c "
from orchestrator.approval_gate import ApprovalGate, SystemHalted, ApprovalTimeout
gate = ApprovalGate()
print(f'Poll interval: {gate.poll_interval}s')
print(f'Timeout: {gate.timeout_seconds}s')
print(f'HALT check: {gate.check_halt()}')
"
```

**Expected output:**
```
Poll interval: 2s
Timeout: 3600s
HALT check: False
```

**Verification:**
- `wait_for_approval()` blocks until frontmatter status changes
- Returns `TaskStatus.APPROVED` or `TaskStatus.REJECTED`
- Raises `SystemHalted` if `HALT.md` appears during wait
- Raises `ApprovalTimeout` if timeout exceeded
- Logs progress every 15 seconds

---

### Task 2.6: Claude Bridge — DONE

**Description:** Build the interface to Claude Code CLI. Constructs prompts from templates, shells out to `claude -p`, and parses responses. Falls back to simulated responses when CLI is unavailable.

**Files to create:**
```
orchestrator/claude_bridge.py
orchestrator/prompts/system.md
orchestrator/prompts/plan_task.md
orchestrator/prompts/review_result.md
```

**Commands to run:**
```bash
python -c "
from orchestrator.claude_bridge import generate_plan
plan = generate_plan('Draft a test email to team@example.com')
print(f'Plan length: {len(plan)} chars')
print('Has checklist:', '- [ ] Step' in plan)
"
```

**Expected output:**
```
Plan length: 724 chars
Has checklist: True
```

**Verification:**
- `generate_plan()` returns markdown with `## Proposed Plan` checklist
- `call_claude()` tries CLI first, falls back to simulation
- `review_result()` asks Claude to verify action output
- Prompt templates load from `orchestrator/prompts/`
- Context loads from `vault/context/` (user-profile, tools-registry)

---

### Task 2.7: Action Dispatcher + MCP Client — DONE

**Description:** Build the dispatcher that parses plan steps and routes them to MCP tool handlers. Includes a minimal MCP client that communicates with the demo server via subprocess/stdio JSON-RPC.

**Files to create:**
```
orchestrator/action_dispatcher.py
```

**Commands to run:**
```bash
python -c "
from orchestrator.action_dispatcher import ActionDispatcher
d = ActionDispatcher()
plan = '- [ ] Step 1: Test (tool: draft_email, approval: yes)'
steps = d.parse_plan_steps(plan)
print(f'Steps parsed: {len(steps)}')
print(f'Tool: {steps[0][\"tool\"]}')
"
```

**Expected output:**
```
Steps parsed: 1
Tool: draft_email
```

**Verification:**
- `parse_plan_steps()` extracts tool name and approval flag from checklist lines
- `execute_steps()` runs each step through the appropriate handler
- `_handle_draft_email()` calls real MCP server, creates file in `vault/drafts/`
- `_handle_create_file()` calls real MCP server, creates file on disk
- `MCPClient.call_tool()` spawns node process, sends JSON-RPC, parses response
- `format_results_markdown()` produces clean markdown for the task file

---

### Task 2.8: MCP Demo Server — DONE

**Description:** Build the Node.js MCP server with two tools: `draft_email` (saves email draft to vault) and `create_file` (creates a file on disk).

**Files to create:**
```
mcp-servers/demo-server/index.js
mcp-servers/demo-server/tools/draft_email.js
mcp-servers/demo-server/tools/create_file.js
mcp-servers/demo-server/package.json
```

**Commands to run:**
```bash
cd mcp-servers/demo-server && npm install && timeout 3 node index.js 2>&1 || true
```

**Expected output:**
```
[MCP] ai-employee-demo server running on stdio
```

**Verification:**
- Server starts without errors on stdio transport
- `draft_email` creates markdown files in `vault/drafts/` with frontmatter
- `create_file` creates files at specified paths with content
- `create_file` rejects path traversal (`..` in paths)
- `create_file` rejects overwrites unless `overwrite: true`
- Both tools return structured JSON results

---

### Task 2.9: Dashboard Updater — DONE

**Description:** Build the module that rewrites `vault/dashboard.md` with live system status, pending approvals, recent action log entries, and active tasks.

**Files to create:**
```
orchestrator/dashboard.py
```

**Commands to run:**
```bash
python -c "
from orchestrator.dashboard import DashboardUpdater
du = DashboardUpdater()
du.update(orchestrator_status='Running')
print('Dashboard updated')
"
```

**Expected output:** `vault/dashboard.md` rewritten with current timestamp and status table.

**Verification:**
- System status table shows component states
- Pending approvals section lists `awaiting-approval` tasks with Obsidian links
- Recent actions table shows last 5 log entries
- Active tasks section lists in-progress tasks
- Kill switch reminder in footer
- YAML frontmatter includes `updated` timestamp

---

### Task 2.10: Main Orchestrator Loop — DONE

**Description:** Build the entry point (`run.py`) that ties all components into a continuous poll loop: check HALT → scan triggers → load tasks → plan → approve → execute → log → archive → update dashboard.

**Files to create:**
```
orchestrator/run.py
```

**Commands to run:**
```bash
python -m orchestrator.run
# (Ctrl+C to stop)
```

**Expected output:**
```
╔══════════════════════════════════════════════════════════════╗
║            PERSONAL AI EMPLOYEE — BRONZE MVP                ║
║                  Orchestrator Engine                        ║
╚══════════════════════════════════════════════════════════════╝

Orchestrator starting...
  Vault:     C:\...\vault
  Tasks dir: C:\...\vault\tasks
  Logs dir:  C:\...\vault\logs
  Poll:      3s
```

**Verification:**
- Starts and polls continuously
- Detects and consumes `.trigger` files
- Processes tasks through all 4 phases (plan → approve → execute → complete)
- Handles errors gracefully (logs, sets failed, archives)
- Respects HALT.md kill switch (pauses until removed)
- Updates dashboard every cycle
- Clean shutdown on Ctrl+C

---

## Phase 3: Automation

### Task 3.1: File Watcher — DONE

**Description:** Build the watchdog-based file watcher that monitors `vault/inbox/` for new markdown files, validates frontmatter, sets status to `pending`, moves to `vault/tasks/`, and writes a `.trigger` file.

**Files to create:**
```
watchers/file_watcher.py
watchers/config.py
```

**Commands to run:**
```bash
python -m watchers.file_watcher
# In another terminal:
cp vault/inbox/_demo-task.md vault/inbox/2026-02-12_test-task.md
```

**Expected output:**
```
[WATCHER] Watching: C:\...\vault\inbox
[WATCHER] New file detected: 2026-02-12_test-task.md
[WATCHER] Task moved to: 2026-02-12_test-task.md
[WATCHER] Trigger written for task: task-20260212-demo
```

**Verification:**
- Detects new `.md` files in `vault/inbox/` (ignores `_`-prefixed templates)
- Validates YAML frontmatter (requires `id` and `status`)
- Sets `status: pending` in frontmatter
- Moves file to `vault/tasks/`
- Writes `.trigger` file with task ID
- Logs warnings for invalid files (doesn't crash)

---

### Task 3.2: End-to-End Integration Test — DONE

**Description:** Verify the complete pipeline: watcher → trigger → orchestrator → Claude plan → approval → MCP execution → audit log → archive → dashboard.

**Files to create:** None (test script only)

**Commands to run:**
```bash
# Clean state
rm -f vault/tasks/*.md vault/tasks/.trigger vault/tasks/archive/*.md
rm -f vault/logs/2026-*.md vault/drafts/*.md

# Run the full pipeline test
python -c "
from pathlib import Path
import shutil
from watchers.utils.markdown_parser import update_frontmatter, parse_frontmatter
from orchestrator.task_manager import TaskManager, TaskStatus
from orchestrator.claude_bridge import generate_plan
from orchestrator.action_dispatcher import ActionDispatcher, format_results_markdown
from orchestrator.dashboard import DashboardUpdater
from orchestrator.logger import audit

# Setup
inbox = Path('vault/inbox/2026-02-12_test.md')
inbox.write_text(open('vault/inbox/_demo-task.md').read(), encoding='utf-8')
update_frontmatter(inbox, {'status': 'pending'})
shutil.move(str(inbox), 'vault/tasks/2026-02-12_test.md')
Path('vault/tasks/.trigger').write_text('task-20260212-demo')

# Run pipeline
tm = TaskManager(); d = ActionDispatcher(); dash = DashboardUpdater()
tm.check_trigger()
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
print('END-TO-END: PASSED')
"
```

**Expected output:**
```
END-TO-END: PASSED
```

**Verification:**
- Task moves through all lifecycle states without error
- Plan and results are written to task file
- Audit logs created in `vault/logs/`
- Email draft created in `vault/drafts/` (via real MCP)
- Task archived in `vault/tasks/archive/`
- Dashboard updated

---

### Task 3.3: Unit Tests — TODO

**Description:** Write pytest unit tests for the core modules: markdown parser, task manager, approval gate, and file watcher.

**Files to create:**
```
tests/test_markdown_parser.py
tests/test_task_manager.py
tests/test_approval_gate.py
tests/test_file_watcher.py
tests/conftest.py          (shared fixtures: temp vault dirs)
```

**Commands to run:**
```bash
pip install pytest
pytest tests/ -v
```

**Expected output:**
```
tests/test_markdown_parser.py::test_parse_valid ........... PASSED
tests/test_markdown_parser.py::test_parse_no_frontmatter .. PASSED
tests/test_markdown_parser.py::test_validate_missing ....... PASSED
tests/test_markdown_parser.py::test_update_frontmatter ..... PASSED
tests/test_task_manager.py::test_load_task ................. PASSED
tests/test_task_manager.py::test_valid_transitions ......... PASSED
tests/test_task_manager.py::test_invalid_transition ........ PASSED
tests/test_task_manager.py::test_archive ................... PASSED
tests/test_approval_gate.py::test_halt_detection ........... PASSED
tests/test_file_watcher.py::test_process_valid_task ........ PASSED
```

**Verification:**
- All tests pass
- Tests use temporary directories (no vault pollution)
- Task manager tests verify state transition enforcement
- Parser tests cover edge cases (no frontmatter, missing fields)

---

### Task 3.4: HALT Kill Switch Verification — DONE

**Description:** Verify the kill switch works: creating `vault/HALT.md` pauses the orchestrator, deleting it resumes.

**Files to create:** None

**Commands to run:**
```bash
# With orchestrator running:
# Create HALT.md
echo "# HALTED" > vault/HALT.md
# Observe: orchestrator prints "HALT.md detected — system paused"
# Remove HALT.md
rm vault/HALT.md
# Observe: orchestrator prints "HALT.md removed — resuming"
```

**Expected output:** Orchestrator pauses and resumes cleanly.

**Verification:**
- Orchestrator stops processing tasks when HALT.md exists
- Orchestrator resumes when HALT.md is deleted
- Dashboard shows "HALTED" status during pause
- Approval gate also checks HALT.md (raises SystemHalted)

---

## Phase 4: Demo & Docs

### Task 4.1: Constitution Document — DONE

**Description:** Write the system constitution defining architecture rules, naming standards, safety rules, coding standards, and error handling.

**Files to create:**
```
docs/CONSTITUTION.md
```

**Commands to run:** None (document only)

**Expected output:** 9-section markdown document covering all system rules.

**Verification:**
- Covers: architecture, naming, agent behavior, safety tiers, coding standards, logging, errors, deliverables
- Defines T0–T4 risk tiers with approval requirements
- Defines Bronze → Silver upgrade path
- Defines constitutional amendment process

---

### Task 4.2: Specification Document — DONE

**Description:** Write the full system specification with directory tree, component responsibilities, step-by-step behavior, demo scenario, and state machine diagram.

**Files to create:**
```
docs/SPECIFICATION.md
```

**Commands to run:** None (document only)

**Expected output:** Complete spec with ASCII diagrams and config defaults.

**Verification:**
- Directory tree matches actual project structure
- Component table covers all modules
- 8-phase task lifecycle fully described
- Demo scenario includes 3-minute timed script
- State machine diagram shows all 9 states and transitions

---

### Task 4.3: Architecture Document — DONE

**Description:** Write the architecture document with visual ASCII diagrams for all four layers, data flow, security boundaries, and technology stack.

**Files to create:**
```
docs/ARCHITECTURE.md
```

**Commands to run:** None (document only)

**Expected output:** Architecture doc with 7 ASCII diagrams.

**Verification:**
- High-level 4-layer diagram
- Detailed component architecture with code references
- Data flow: happy path, error path, kill switch
- File-level dependency map
- Security boundary diagram
- Technology stack table
- Bronze limitations table

---

### Task 4.4: Demo Script — DONE

**Description:** Write a timed 3-minute demo runbook with pre-demo setup, live script with exact commands, backup troubleshooting table, and key talking points.

**Files to create:**
```
docs/DEMO-SCRIPT.md
vault/inbox/_demo-task.md
```

**Commands to run:** None (document only)

**Expected output:** Step-by-step demo with timestamps and exact terminal commands.

**Verification:**
- Pre-demo setup section with cleanup commands
- 4 timed sections: intro, trigger, approval, execution
- Demo task file ready to copy into inbox
- Troubleshooting table for common problems
- 6 key talking points for judges

---

### Task 4.5: Vault Templates — DONE

**Description:** Create all Obsidian vault template files: dashboard, task template, user profile, tools registry, log template, HALT switch.

**Files to create:**
```
vault/dashboard.md
vault/inbox/_template.md
vault/context/user-profile.md
vault/context/tools-registry.md
vault/logs/_log-template.md
vault/HALT.md.disabled
```

**Commands to run:** None (templates only)

**Expected output:** All template files with correct YAML frontmatter.

**Verification:**
- Dashboard has system status table, pending approvals, recent actions
- Task template has all required frontmatter fields
- User profile has editable identity and preferences sections
- Tools registry documents both MCP tools with risk tiers
- HALT.md.disabled has instructions for activation

---

### Task 4.6: README — TODO

**Description:** Write the project README with overview, quick start, architecture summary, demo instructions, and contribution guide.

**Files to create:**
```
README.md
```

**Commands to run:** None (document only)

**Expected output:** README with badges, setup instructions, and screenshots section.

**Verification:**
- Project title and one-line description
- Quick start: 4 commands to get running
- Architecture diagram (simplified from ARCHITECTURE.md)
- Demo instructions pointing to DEMO-SCRIPT.md
- Link to CONSTITUTION.md and SPECIFICATION.md
- Tech stack list
- License section

---

### Task 4.7: Hackathon Packaging — TODO

**Description:** Final preparation for hackathon submission: clean up test artifacts, verify git history, ensure `.env` is not committed, create a release tag.

**Files to create:**
```
.gitattributes
```

**Commands to run:**
```bash
# Clean test artifacts
rm -f vault/tasks/*.md vault/tasks/.trigger
rm -f vault/tasks/archive/*.md
rm -f vault/logs/2026-*.md
rm -f vault/drafts/*.md vault/output/*.md

# Verify no secrets committed
grep -r "sk-ant-" . --include="*.py" --include="*.js" --include="*.md" && echo "SECRETS FOUND" || echo "Clean"

# Final commit
git add -A
git commit -m "Bronze MVP: Personal AI Employee — hackathon ready"

# Tag release
git tag v1.0.0-bronze -m "Bronze tier MVP for hackathon demo"
```

**Expected output:** Clean repo with tagged release, no secrets, no test artifacts.

**Verification:**
- `git status` shows clean working tree
- `.env` is in `.gitignore` and not committed
- No API keys in any committed file
- `vault/logs/` and `vault/tasks/archive/` are empty
- All 4 docs exist: CONSTITUTION, SPECIFICATION, ARCHITECTURE, DEMO-SCRIPT
- Tag `v1.0.0-bronze` exists

---

## Progress Summary

| Phase | Tasks | Done | TODO |
|---|---|---|---|
| **Phase 1: Setup** | 5 | 4 | 1 (git init) |
| **Phase 2: Core System** | 10 | 10 | 0 |
| **Phase 3: Automation** | 4 | 3 | 1 (unit tests) |
| **Phase 4: Demo & Docs** | 7 | 5 | 2 (README, packaging) |
| **TOTAL** | **26** | **22** | **4** |

### Remaining TODO Tasks

| ID | Task | Priority | Effort |
|---|---|---|---|
| 1.5 | Git repository init | Medium | 5 min |
| 3.3 | Unit tests (pytest) | Medium | 30 min |
| 4.6 | README.md | High | 15 min |
| 4.7 | Hackathon packaging | High | 10 min |

### Critical Path to Demo

All critical-path tasks are **DONE**:
1. File watcher detects tasks
2. Orchestrator plans via Claude
3. Approval gate pauses for human
4. MCP server executes real actions
5. Audit logger records everything
6. Dashboard shows live status
7. Kill switch works

The system is **demo-ready now**. Remaining tasks are polish (tests, README, git).
