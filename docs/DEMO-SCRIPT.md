# DEMO-SCRIPT.md — Hackathon Live Demo Runbook

> **Time:** 3 minutes
> **Setup:** Split screen — Terminal (left) + Obsidian vault (right)

---

## Pre-Demo Setup (2 minutes before)

```bash
# 1. Clean any previous test data
cd "Hackathon 0"
rm -f vault/tasks/*.md vault/tasks/.trigger vault/tasks/archive/*.md
rm -f vault/logs/2026-*.md vault/drafts/*.md vault/output/*.md

# 2. Start the orchestrator (Terminal 1)
python -m orchestrator.run

# 3. Start the file watcher (Terminal 2)
python -m watchers.file_watcher

# 4. Open Obsidian with the vault/ folder
#    Set dashboard.md as the home page
```

Verify both terminal windows show "Running" / "Watching" status.

---

## Live Demo Script

### [0:00–0:30] Introduction

> "This is a Personal AI Employee — a local-first autonomous agent
> that plans and executes tasks with full human oversight.
> Everything runs locally. No cloud databases. Full audit trail."

**Show:** Obsidian dashboard — system status shows Running.

---

### [0:30–1:00] Trigger a Task

> "I drop a task into the inbox — just a markdown file."

**Action:** Copy the demo task file into the inbox:

```bash
cp vault/inbox/_demo-task.md vault/inbox/2026-02-12_send-weekly-report.md
```

**Show in Terminal 1 (Watcher):**
```
[WATCHER] New file detected: 2026-02-12_send-weekly-report.md
[WATCHER] Task moved to: vault/tasks/
[WATCHER] Trigger written
```

**Show in Terminal 2 (Orchestrator):**
```
Trigger received: task-20260212-demo
PROCESSING: Send Weekly Report
[Phase 1] PLANNING...
Claude responded (724 chars)
Plan written to task file
```

---

### [1:00–1:45] AI Reasoning + Approval Gate

> "The AI analyzed the task and generated a plan.
> Nothing happens without my approval."

**Switch to Obsidian:**
- Open the task file in `vault/tasks/`
- Show the `## Proposed Plan` section with checklist
- Show the `## Draft Output` section with email draft
- Show `dashboard.md` → "1 pending approval"

> "I review the draft, and if it looks good, I approve it."

**Action:** Edit the frontmatter in Obsidian:
Change `status: awaiting-approval` → `status: approved`

**Show in Terminal (Orchestrator):**
```
APPROVED: Send Weekly Report
[Phase 3] EXECUTING VIA MCP SERVER...
[MCP] draft_email tool called
  -> Success (696ms)
```

---

### [2:15–2:45] Execution + Results

> "The approved action executed through a Model Context Protocol server.
> A real email draft was created in the vault."

**Show in Obsidian:**
- Open `vault/drafts/` — show the email draft markdown file
- Open the archived task in `vault/tasks/archive/` — show the execution results
- Open `dashboard.md` — show the updated action history

---

### [2:45–3:00] Audit Trail + Kill Switch

> "Everything is logged. Every action, every approval, fully auditable."

**Show:** `vault/logs/` — scroll through log entries

> "And if anything goes wrong — kill switch."

**Action:** Create `vault/HALT.md`

**Show in Terminal:**
```
HALT.md detected — system paused
```

**Action:** Delete `vault/HALT.md`

**Show:** System resumes.

> "Local-first. Human-in-the-loop. Fully auditable.
> This is the Bronze MVP — and it's ready for Silver."

---

## Demo Task File

Save this as `vault/inbox/_demo-task.md` for easy copying during the demo:

```markdown
---
id: task-20260212-demo
status: new
priority: high
source: manual
tags: [email, weekly-report, demo]
approval_required: true
created: 2026-02-12T15:00:00
---

## Request

Draft and send the weekly status report email to team@example.com.

Include:
- Progress on Project Alpha (80% complete, on track)
- Blocker: waiting on API credentials from vendor (ETA: Feb 15)
- Next week: finalize integration testing, begin UAT

## Context

Weekly report for the engineering team. Keep it professional
but friendly. Use bullet points for clarity.
```

---

## Backup: If Something Breaks

| Problem | Fix |
|---|---|
| Watcher not detecting files | Restart: `python -m watchers.file_watcher` |
| Orchestrator stuck | Check for HALT.md, delete if present |
| Claude CLI not found | System uses simulated response (still works) |
| MCP server error | Check Node.js installed: `node --version` |
| Task stuck in awaiting-approval | Edit frontmatter manually to `approved` |
| Dashboard not updating | Orchestrator updates it every cycle automatically |

---

## Key Talking Points

1. **Local-first**: Everything on disk, no cloud dependency
2. **Human-in-the-loop**: Every action requires approval (Bronze)
3. **Auditable**: Complete log trail in markdown
4. **Modular**: Watchers, Orchestrator, Vault, MCP servers are independent
5. **Extensible**: Bronze → Silver upgrade path is designed in
6. **Obsidian-native**: Dashboard, tasks, and logs all viewable in Obsidian
