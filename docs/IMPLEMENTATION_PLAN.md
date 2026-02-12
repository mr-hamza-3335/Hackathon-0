# IMPLEMENTATION_PLAN.md — Execution Roadmap

> **Project:** Personal AI Employee — Autonomous Digital FTE
> **Timeline:** 2-Day Hackathon Sprint
> **Last Updated:** 2026-02-12
> **Current State:** Bronze MVP complete, tagged `v1.0.0-bronze`

---

## Executive Summary

The Bronze MVP is **fully built, tested, and tagged**. This plan documents the sprint that produced it (Day 1) and charts the path forward (Day 2) — hardening the system, adding real Claude integration, and polishing the demo for judges.

```
DAY 1 (DONE): Foundation → Core System → Integration → Verification
DAY 2 (NEXT): Harden → Real Claude → Demo Polish → Present
```

---

## Day 1: Build Sprint (COMPLETED)

### Hour-by-Hour Milestones

| Time | Block | Milestone | Status |
|---|---|---|---|
| **0:00–0:30** | Setup | Constitution + Specification written | DONE |
| **0:30–1:00** | Setup | Architecture doc + scaffold script | DONE |
| **1:00–1:15** | Setup | Run `init_project.sh`, install deps | DONE |
| **1:15–2:00** | Core | Config loader, audit logger, markdown parser | DONE |
| **2:00–3:00** | Core | Task manager (9-state machine), approval gate | DONE |
| **3:00–3:45** | Core | Claude bridge (CLI + simulation fallback) | DONE |
| **3:45–4:30** | Core | Action dispatcher + MCP client wiring | DONE |
| **4:30–5:00** | Core | Main orchestrator loop (`run.py`) | DONE |
| **5:00–5:30** | MCP | Demo MCP server (draft_email, create_file) | DONE |
| **5:30–6:00** | MCP | Wire dispatcher to real MCP calls via stdio | DONE |
| **6:00–6:30** | Test | End-to-end pipeline verification | DONE |
| **6:30–7:00** | Test | Dashboard updater, live demo dry run | DONE |
| **7:00–7:45** | Polish | 43 unit tests (all passing) | DONE |
| **7:45–8:00** | Ship | README, git init, commit, tag `v1.0.0-bronze` | DONE |

### Day 1 Deliverables Achieved

- [x] 4-layer architecture (watchers, orchestrator, vault, MCP)
- [x] 8 orchestrator modules, all production-ready
- [x] MCP server with 2 real tools
- [x] File watcher with watchdog
- [x] Human approval gate via Obsidian frontmatter
- [x] HALT.md kill switch
- [x] Structured audit logging
- [x] Live dashboard auto-update
- [x] 43/43 tests passing
- [x] 5 documentation files
- [x] Demo task ready in inbox
- [x] Git repo initialized and tagged

---

## Day 2: Harden + Demo Sprint

### Hour-by-Hour Milestones

| Time | Block | Milestone | Target |
|---|---|---|---|
| **0:00–0:30** | Review | Assess Day 1 output, prioritize Day 2 | Plan finalized |
| **0:30–1:30** | Claude | Real Claude CLI integration (replace simulation) | Live AI planning |
| **1:30–2:30** | Claude | Dynamic plan parsing (extract email fields from Claude response) | Smart dispatch |
| **2:30–3:00** | MCP | Add email content from Claude plan to draft_email calls | Real email drafts |
| **3:00–3:30** | Harden | Error edge cases: corrupt files, missing frontmatter, disk full | Robust error handling |
| **3:30–4:00** | Harden | Concurrent watcher + orchestrator stability test | 10-task stress test |
| **4:00–4:30** | Demo | Create 2-3 demo scenarios (email, file creation, mixed) | Demo variety |
| **4:30–5:00** | Demo | Record terminal + Obsidian screencast for backup | Backup demo video |
| **5:00–5:30** | Demo | Dry run the 3-minute demo script 3 times | Smooth delivery |
| **5:30–6:00** | Demo | Final git commit, update TASKS.md progress | Clean final state |
| **6:00–6:30** | Present | Setup projector/screen, open terminals | Ready to present |
| **6:30–7:00** | Present | **LIVE DEMO** | Ship it |

---

## Task Dependency Graph

```
Phase 1: SETUP
  1.1 Scaffold ──────────────────────────────────────────────┐
  1.2 Python deps ──┐                                       │
  1.3 Node deps ────┤                                       │
  1.4 .env config ──┘                                       │
                    │                                        │
Phase 2: CORE      ▼                                        │
  2.1 Markdown parser ──────┐                               │
                            │                               │
  2.2 Config loader ────────┤                               │
                            ▼                               │
  2.4 Task manager ─────────┬──→ 2.5 Approval gate         │
                            │                               │
  2.3 Audit logger ─────────┤                               │
                            ▼                               │
  2.6 Claude bridge ────────┤                               │
                            │                               │
  2.7 Action dispatcher ◀───┤──→ 2.8 MCP server            │
                            │                               │
  2.9 Dashboard updater ◀───┘                               │
                            │                               │
  2.10 Main loop (run.py) ◀─┘   (depends on ALL above)     │
                                                            │
Phase 3: AUTOMATION                                         │
  3.1 File watcher ◀────────────────────────────────────────┘
  3.2 E2E integration test ◀── 2.10 + 3.1
  3.3 Unit tests ◀──────────── 2.1–2.10
  3.4 Kill switch test ◀────── 2.5 + 2.10

Phase 4: DEMO & DOCS
  4.1 Constitution ──┐
  4.2 Specification ──┤ (can be done in parallel with code)
  4.3 Architecture ───┤
  4.4 Demo script ────┤──→ 4.7 Hackathon packaging
  4.5 Vault templates ┤
  4.6 README ─────────┘
  4.7 Packaging ◀──────── ALL above
```

### Critical Path

```
Scaffold → Parser → Config → Task Manager → Claude Bridge →
Action Dispatcher → Main Loop → File Watcher → E2E Test → Package
```

**Critical path length:** 10 tasks. All 10 are DONE.

### Parallelizable Groups

| Group | Tasks | Can Run Simultaneously |
|---|---|---|
| A | Config + Logger + Parser | Yes (no deps on each other) |
| B | Task Manager + Approval Gate | Yes (both depend on A) |
| C | Claude Bridge + MCP Server | Yes (independent implementations) |
| D | All documentation (4.1–4.6) | Yes (parallel with code phases) |

---

## Risk Mitigation Strategies

### R1: Claude CLI Not Available

| Risk | Claude Code CLI not installed or API key missing |
|---|---|
| Probability | Medium |
| Impact | High — no AI reasoning |
| Mitigation | **DONE** — `claude_bridge.py` has `_simulate_response()` fallback that generates a realistic plan without the CLI. Demo works fully without an API key. |
| Detection | Console log: "Claude CLI not found — using simulated response" |

### R2: MCP Server Fails to Start

| Risk | Node.js not installed or MCP SDK broken |
|---|---|
| Probability | Low |
| Impact | Medium — actions fail but planning still works |
| Mitigation | Action dispatcher catches errors per-step. Failed steps are logged but don't crash the system. Demo can show planning + approval without execution. |
| Detection | Audit log entry with `status: failure` |

### R3: File Permissions / Disk Issues

| Risk | Can't write to vault directories |
|---|---|
| Probability | Low |
| Impact | High — system can't function |
| Mitigation | `init_project.sh` creates all directories upfront. Config loader validates paths on startup. All `mkdir` calls use `parents=True, exist_ok=True`. |
| Detection | Python exception on startup |

### R4: Demo Computer Different from Dev

| Risk | Demo environment missing deps or has different Python version |
|---|---|
| Probability | Medium |
| Impact | High — demo fails |
| Mitigation | (1) Test on demo machine 30 min before. (2) `requirements.txt` pins deps. (3) Record a backup screencast video. (4) Simulation fallback means zero external dependencies needed. |
| Detection | Pre-demo `python -m pytest tests/ -q` check |

### R5: Obsidian Not Installed on Demo Machine

| Risk | No Obsidian available to show approval flow |
|---|---|
| Probability | Medium |
| Impact | Medium — approval still works via any text editor |
| Mitigation | Approval gate reads raw YAML frontmatter. Any text editor can change `status: approved`. VS Code, Notepad, or even `sed` works. |
| Detection | N/A — editor-agnostic by design |

### R6: Task Gets Stuck in Awaiting-Approval

| Risk | Human forgets to approve, or saves wrong status value |
|---|---|
| Probability | Medium |
| Impact | Low — system just waits |
| Mitigation | (1) 60-minute timeout auto-fails the task. (2) Dashboard shows pending approvals. (3) Console prints file path to edit. (4) Demo script pre-plans exact edit. |
| Detection | Console: "Still waiting for approval... (Xm remaining)" |

### R7: Race Condition Between Watcher and Orchestrator

| Risk | Orchestrator reads task file while watcher is still writing |
|---|---|
| Probability | Low |
| Impact | Low — parse error, task skipped |
| Mitigation | Watcher writes file first, moves it second, writes trigger last. Orchestrator only acts on trigger files. Sequential by design. |
| Detection | Watcher and orchestrator are separate processes with clear handoff |

---

## Demo Readiness Checklist

### Pre-Demo (T-30 minutes)

- [ ] Demo machine has Python 3.11+ installed
- [ ] Demo machine has Node.js 20+ installed
- [ ] `pip install -r requirements.txt` succeeds
- [ ] `cd mcp-servers/demo-server && npm install` succeeds
- [ ] `python -m pytest tests/ -q` shows 43 passed
- [ ] `.env` file exists (even if API key is placeholder)
- [ ] Obsidian installed OR text editor ready
- [ ] Terminal supports UTF-8 (for ASCII banner)

### Environment (T-15 minutes)

- [ ] Clean test artifacts: `rm -f vault/tasks/*.md vault/logs/2026-*.md`
- [ ] Terminal 1 ready: `python -m orchestrator.run`
- [ ] Terminal 2 ready: `python -m watchers.file_watcher`
- [ ] Obsidian open with `vault/` as vault root
- [ ] `dashboard.md` set as Obsidian home page
- [ ] Demo task file ready: `vault/inbox/_demo-task.md`
- [ ] Screen layout: terminal left, Obsidian right

### Demo Flow (T-5 minutes)

- [ ] Both processes show "Running" / "Watching"
- [ ] Dashboard shows all components active
- [ ] Know the exact copy command: `cp vault/inbox/_demo-task.md vault/inbox/2026-02-12_send-weekly-report.md`
- [ ] Know the exact frontmatter edit: `status: approved`
- [ ] Practiced the 3-minute script at least twice
- [ ] Backup: screencast recording available

### Post-Demo Verification

- [ ] Task in `vault/tasks/archive/` with `status: completed`
- [ ] Email draft in `vault/drafts/` (if MCP ran)
- [ ] 10+ audit log entries in `vault/logs/`
- [ ] Dashboard shows completion in recent actions

---

## Bronze Completion Criteria

### Functional Requirements — ALL MET

| # | Requirement | Status | Evidence |
|---|---|---|---|
| F1 | File watcher detects new tasks in inbox | DONE | `watchers/file_watcher.py` — 5 tests passing |
| F2 | Orchestrator reads task, generates plan | DONE | `orchestrator/run.py` + `claude_bridge.py` |
| F3 | Plan is written to task file as markdown | DONE | `task_manager.write_plan()` — 2 tests passing |
| F4 | Human approval via frontmatter edit | DONE | `approval_gate.py` — 7 tests passing |
| F5 | MCP server executes approved action | DONE | `mcp-servers/demo-server/` — real tool calls verified |
| F6 | Audit log for every action | DONE | `logger.py` — 10 log files per task lifecycle |
| F7 | Dashboard shows system status | DONE | `dashboard.py` — auto-updates every cycle |
| F8 | Kill switch halts system | DONE | `HALT.md` detection in gate + main loop |
| F9 | End-to-end pipeline works | DONE | Full pipeline test passed with real MCP |
| F10 | 3-minute demo possible | DONE | `DEMO-SCRIPT.md` with timed runbook |

### Non-Functional Requirements — ALL MET

| # | Requirement | Status | Evidence |
|---|---|---|---|
| N1 | Local-first (no cloud DB) | DONE | All state in vault markdown |
| N2 | No secrets in code | DONE | `.env.example` with placeholders only |
| N3 | Modular architecture | DONE | 4 layers with strict boundaries |
| N4 | Error handling | DONE | Fail loud, log, stop — never retry infinitely |
| N5 | Typed Python (hints) | DONE | All function signatures typed |
| N6 | Tests pass | DONE | 43/43 passing |
| N7 | Git tagged release | DONE | `v1.0.0-bronze` |

---

## Silver Upgrade Roadmap

### Silver Tier Feature Map

```
SILVER (v2.0.0)
├── Multi-Step Task Chains
│   ├── Chain definition in task frontmatter
│   ├── Intermediate checkpoints between steps
│   ├── Partial completion tracking
│   └── Chain-level rollback
│
├── Smart Approval Tiers
│   ├── T0/T1 auto-approved (no human needed)
│   ├── T2 auto-approved with logging
│   ├── T3 requires human approval (unchanged)
│   └── T4 requires human approval + confirmation
│
├── Enhanced Perception
│   ├── Schedule watcher (cron-based triggers)
│   ├── Email inbox polling (IMAP)
│   ├── Webhook receiver (HTTP endpoint)
│   └── Calendar event triggers
│
├── Real Claude Integration
│   ├── Live Claude CLI calls (no simulation)
│   ├── Context window management
│   ├── Multi-turn reasoning for complex tasks
│   └── Tool use via Claude's native tool calling
│
├── Expanded MCP Tools
│   ├── Real email sending (SMTP/Gmail API)
│   ├── Calendar management (Google Calendar)
│   ├── File system operations (read/write/search)
│   ├── Web search and summarization
│   └── Tool registry with dynamic discovery
│
├── Obsidian Knowledge Graph
│   ├── Task-to-task linking
│   ├── Context graph (tags, topics, entities)
│   ├── Backlinks between logs and tasks
│   └── Search-powered context retrieval
│
└── Structured Logging
    ├── JSON log format alongside markdown
    ├── Log rotation and archival
    ├── Search and filter via vault queries
    └── Daily/weekly digest generation
```

### Silver Implementation Priority

| Priority | Feature | Effort | Impact | Dependencies |
|---|---|---|---|---|
| P0 | Real Claude CLI integration | 2h | High | API key configured |
| P0 | Dynamic plan parsing (extract fields) | 3h | High | Claude integration |
| P1 | Smart approval tiers (T0/T1 auto) | 2h | Medium | Config change only |
| P1 | Schedule watcher (cron) | 3h | Medium | New watcher module |
| P2 | Real email sending (SMTP) | 4h | High | MCP server upgrade |
| P2 | Multi-step task chains | 6h | High | Task manager refactor |
| P3 | Webhook receiver | 4h | Medium | New HTTP server |
| P3 | Obsidian knowledge graph | 4h | Medium | Vault restructure |
| P4 | Expanded MCP tool registry | 8h | High | Per-tool effort |

### Silver Migration Steps

```
1. Branch: git checkout -b silver-upgrade

2. Real Claude (P0):
   - Remove _simulate_response fallback flag
   - Parse Claude's actual structured output
   - Extract email fields (to, subject, body) from ## Draft Output
   - Pass extracted fields to MCP draft_email tool

3. Smart Approval (P1):
   - Add risk_tier field to task frontmatter
   - Modify approval_gate to check tier before waiting
   - Auto-approve T0/T1, log and continue
   - Dashboard shows auto-approved actions differently

4. Schedule Watcher (P1):
   - New watchers/schedule_watcher.py
   - Config: cron expressions in config.yaml
   - Generates task files on schedule

5. Real Email (P2):
   - Upgrade draft_email.js to send via SMTP
   - Add SMTP config to .env
   - Keep draft-first pattern (save draft, then send on approval)

6. Tag: git tag v2.0.0-silver
```

---

## Testing Strategy

### Test Pyramid

```
          ┌───────────────┐
          │   E2E Demo    │  1 test (full pipeline)
          │   (manual)    │
          ├───────────────┤
          │  Integration  │  3 tests (watcher→orchestrator,
          │               │  orchestrator→MCP, approval flow)
          ├───────────────┤
          │  Unit Tests   │  43 tests (parser, task_mgr,
          │               │  approval gate, watcher handler)
          └───────────────┘
```

### Unit Tests (43 — All Passing)

| Module | Tests | Covers |
|---|---|---|
| `test_markdown_parser.py` | 10 | Parse valid/invalid/empty, validate fields, update frontmatter |
| `test_task_manager.py` | 13 | Load, valid/invalid transitions, full happy path, plan, result, archive, triggers |
| `test_approval_gate.py` | 7 | Halt detection, approve, reject, timeout, halt during wait, delayed approval |
| `test_file_watcher.py` | 5 | Valid task, invalid task, ignore dirs/non-md/templates |
| `conftest.py` | — | Shared fixtures: tmp_vault, sample files |

### Integration Tests (Day 2 Target)

| Test | What It Verifies |
|---|---|
| Watcher → Orchestrator | File dropped in inbox triggers orchestrator processing |
| Orchestrator → MCP | Approved plan step results in real MCP tool call |
| Full approval flow | Status change in file is detected within poll interval |

### Manual E2E Test (Pre-Demo)

```bash
# 1. Clean state
rm -f vault/tasks/*.md vault/tasks/.trigger vault/tasks/archive/*.md
rm -f vault/logs/2026-*.md vault/drafts/*.md

# 2. Start system
python -m orchestrator.run &
python -m watchers.file_watcher &

# 3. Trigger
cp vault/inbox/_demo-task.md vault/inbox/2026-02-12_test.md

# 4. Wait for planning (watch terminal)
# 5. Approve: edit vault/tasks/2026-02-12_test.md → status: approved
# 6. Verify:
#    - vault/tasks/archive/2026-02-12_test.md exists
#    - vault/logs/ has new entries
#    - vault/dashboard.md shows completion

# 7. Kill switch test
echo "# HALT" > vault/HALT.md
# Verify: orchestrator pauses
rm vault/HALT.md
# Verify: orchestrator resumes
```

### Test Run Command

```bash
# Quick (just pass/fail)
python -m pytest tests/ -q

# Verbose (see all test names)
python -m pytest tests/ -v

# With coverage (requires pytest-cov)
python -m pytest tests/ --cov=orchestrator --cov=watchers --cov-report=term-missing
```

---

## Sprint Velocity Reference

### Day 1 Actual Output

| Metric | Value |
|---|---|
| Source files created | 20 |
| Documentation files | 6 |
| Lines of code | ~2,500 |
| Lines of documentation | ~4,000 |
| Tests written | 43 |
| Test pass rate | 100% |
| MCP tools | 2 (real, working) |
| Git commits | 1 (clean initial) |
| Bugs found & fixed | 1 (Windows filename colons) |

### Day 2 Expected Output

| Metric | Target |
|---|---|
| Real Claude integration | Working |
| Additional demo scenarios | 2-3 |
| Integration tests added | 3-5 |
| Demo dry runs completed | 3+ |
| Backup screencast | Recorded |
| Final git tag | `v1.1.0-bronze` or `v2.0.0-silver` |

---

*This plan is a living document. Update milestone statuses as work progresses. The Bronze MVP is complete — Day 2 is about making it shine.*
