# CONSTITUTION.md — Personal AI Employee System

> **Version:** 1.0.0-bronze
> **Project:** Personal AI Employee Hackathon — Building Autonomous Digital FTEs
> **Last Updated:** 2026-02-12

---

## 1. System Architecture Rules

### 1.1 Four-Layer Architecture

The system is composed of exactly four layers. No component may blur these boundaries.

| Layer | Responsibility | Technology |
|---|---|---|
| **Perception** | Watch filesystem, APIs, schedules for triggers | Python watcher scripts |
| **Orchestration** | Reason about tasks, plan, decide next action | Claude Code (CLI) |
| **Memory & Dashboard** | Store state, logs, tasks, context | Obsidian vault (markdown) |
| **Action** | Execute approved operations on external systems | MCP servers |

### 1.2 Data Flow Direction

```
Perception → Orchestration → Memory (read/write) → Action
                ↑                                      |
                └──────── feedback loop ───────────────┘
```

- Perception scripts MUST NOT call actions directly.
- Actions MUST only be triggered through the orchestrator.
- Memory is the single source of truth for all system state.

### 1.3 Local-First Privacy

- **No cloud databases.** All persistent state lives in the local Obsidian vault.
- **No telemetry.** Watcher scripts must not phone home.
- **Secrets isolation.** API keys live in `.env` files, never in vault markdown or git history.
- **Network calls** are permitted only to explicitly configured MCP server endpoints and the Claude API.

### 1.4 Bronze → Silver Upgrade Path

| Capability | Bronze (Hackathon MVP) | Silver (Post-Hackathon) |
|---|---|---|
| Task execution | Single-step, human-approved | Multi-step chains with checkpoints |
| Memory | Flat markdown files | Linked knowledge graph in Obsidian |
| Perception | File watcher + cron | Webhooks, email polling, calendar |
| Actions | 2-3 MCP tools | Full MCP tool registry with auth |
| Safety | Approve every action | Risk-tiered auto-approve for low-risk |
| Logging | Append-only markdown | Structured JSON + markdown summary |

---

## 2. Folder and File Naming Standards

### 2.1 Project Root Structure

```
hackathon-0/
├── docs/
│   ├── CONSTITUTION.md          # This file
│   ├── ARCHITECTURE.md          # System diagrams and flow
│   └── DEMO-SCRIPT.md           # Hackathon demo runbook
├── vault/                       # Obsidian vault root
│   ├── inbox/                   # New tasks and triggers land here
│   ├── tasks/                   # Active and completed task files
│   ├── logs/                    # Execution audit logs
│   ├── context/                 # Long-term memory and preferences
│   └── dashboard.md             # Live system status overview
├── watchers/                    # Python perception scripts
│   ├── file_watcher.py
│   ├── schedule_watcher.py
│   └── utils/
├── orchestrator/                # Claude Code integration layer
│   ├── run.py                   # Main orchestrator entry point
│   ├── prompts/                 # System and task prompt templates
│   └── config.yaml              # Orchestrator configuration
├── mcp-servers/                 # MCP action servers
│   ├── email-server/
│   ├── file-server/
│   └── calendar-server/
├── tests/                       # Test suite
├── .env.example                 # Template for secrets
├── .gitignore
├── requirements.txt             # Python dependencies
├── package.json                 # Node dependencies (MCP servers)
└── README.md
```

### 2.2 Naming Conventions

| Item | Convention | Example |
|---|---|---|
| Folders | `kebab-case` | `mcp-servers/` |
| Python files | `snake_case.py` | `file_watcher.py` |
| Node/JS files | `camelCase.js` | `emailServer.js` |
| Vault task files | `YYYY-MM-DD_task-slug.md` | `2026-02-12_draft-weekly-report.md` |
| Vault log files | `YYYY-MM-DD_HH-MM_event.md` | `2026-02-12_14-30_email-sent.md` |
| Config files | `lowercase.yaml` or `.json` | `config.yaml` |
| Environment files | `.env`, `.env.example` | Never committed to git |

### 2.3 Vault Frontmatter Standard

Every task file in the vault MUST include YAML frontmatter:

```yaml
---
id: task-20260212-001
status: pending | in-progress | awaiting-approval | completed | failed
priority: high | medium | low
created: 2026-02-12T14:30:00
source: watcher:file | watcher:schedule | manual
assigned_to: orchestrator
tags: [email, weekly-report]
approval_required: true
---
```

---

## 3. Agent Behavior Constraints

### 3.1 Identity

The AI Employee operates under these rules:

- It is an **assistant**, not an autonomous actor. It proposes; the human disposes.
- It MUST NOT impersonate the user in any communication without explicit approval.
- It MUST identify AI-generated content when producing output sent to third parties.

### 3.2 Scope of Action

- The agent operates ONLY within the boundaries of its configured MCP tools.
- It MUST NOT install software, modify system settings, or access files outside the project tree.
- It MUST NOT make financial transactions, delete production data, or send communications without approval.

### 3.3 Task Lifecycle

```
TRIGGER → PERCEIVE → PLAN → PROPOSE → [APPROVE] → EXECUTE → LOG → VERIFY
```

1. **Trigger**: A watcher detects an event or a schedule fires.
2. **Perceive**: The watcher writes a task file to `vault/inbox/`.
3. **Plan**: The orchestrator reads the task, gathers context from `vault/context/`, and reasons about steps.
4. **Propose**: The orchestrator writes a plan to the task file under a `## Proposed Plan` section.
5. **Approve**: The human reviews and sets `status: approved` (Bronze requires this for ALL actions).
6. **Execute**: The orchestrator calls MCP servers to carry out approved actions.
7. **Log**: Every action and its result is appended to `vault/logs/`.
8. **Verify**: The orchestrator checks the result and updates the task status.

### 3.4 Failure Behavior

- On error, the agent MUST set the task to `status: failed` with an error summary.
- The agent MUST NOT retry failed actions more than **once** without human review.
- The agent MUST NOT silently swallow exceptions. All errors are logged.

---

## 4. Safety and Approval Rules

### 4.1 Action Risk Tiers

| Tier | Risk Level | Examples | Approval Required (Bronze) |
|---|---|---|---|
| **T0 — Read** | None | Read vault files, check status | No |
| **T1 — Internal Write** | Low | Write to vault, update task status | No |
| **T2 — External Read** | Low | Fetch email subjects, read calendar | Yes |
| **T3 — External Write** | High | Send email, create calendar event | Yes |
| **T4 — Destructive** | Critical | Delete files, modify permissions | Always Yes (even Silver) |

### 4.2 Approval Mechanism (Bronze)

- The orchestrator writes the proposed action to the task file.
- The dashboard (`vault/dashboard.md`) surfaces pending approvals.
- The human edits the task frontmatter: `status: approved` or `status: rejected`.
- The orchestrator polls for status changes before executing.

### 4.3 Guardrails

- **Rate limiting**: No more than 10 external actions per hour without explicit override.
- **Content review**: Any outbound message (email, Slack) MUST be written to the vault for review before sending.
- **Rollback plan**: Every T3/T4 action MUST include a rollback description in the task plan.
- **Kill switch**: A `vault/HALT.md` file, if present, immediately stops all orchestrator activity.

---

## 5. Coding Standards

### 5.1 Python (Watchers, Orchestrator)

- **Version**: Python 3.11+
- **Style**: PEP 8, enforced by `ruff`
- **Type hints**: Required on all function signatures
- **Imports**: stdlib → third-party → local, separated by blank lines
- **Dependencies**: Pinned in `requirements.txt` with exact versions
- **Entry points**: Each script must be runnable with `python -m <module>`
- **Async**: Use `asyncio` for I/O-bound watchers; avoid threads unless necessary

```python
# Example function signature
async def watch_inbox(vault_path: Path, interval: int = 5) -> None:
    """Watch the vault inbox for new task files."""
    ...
```

### 5.2 Node.js (MCP Servers)

- **Version**: Node 20 LTS+
- **Style**: ESLint with recommended rules
- **Module system**: ES modules (`"type": "module"` in package.json)
- **Dependencies**: Pinned in `package-lock.json`
- **MCP compliance**: All servers implement the MCP protocol specification
- **Error responses**: Return structured error objects, never raw stack traces

```javascript
// Example MCP tool handler
export async function handleSendEmail({ to, subject, body }) {
  // Validate inputs before any external call
  if (!to || !subject) {
    return { error: "Missing required fields: to, subject" };
  }
  // ...
}
```

### 5.3 Shared Standards

- **No hardcoded secrets** — use environment variables via `.env`
- **No hardcoded paths** — use config files or CLI arguments
- **UTF-8 encoding** everywhere
- **LF line endings** (configure `.gitattributes`)

---

## 6. Logging and Audit Requirements

### 6.1 What Gets Logged

Every orchestrator action MUST produce a log entry containing:

| Field | Description |
|---|---|
| `timestamp` | ISO 8601 with timezone |
| `task_id` | Reference to the originating task |
| `action` | What was attempted |
| `tool` | Which MCP server/tool was called |
| `input_summary` | Sanitized summary of inputs (no secrets) |
| `output_summary` | Summary of result |
| `status` | `success` or `failure` |
| `error` | Error message if failed |
| `duration_ms` | Execution time |

### 6.2 Log Format (Bronze)

Append-only markdown in `vault/logs/`:

```markdown
---
timestamp: 2026-02-12T14:35:22+00:00
task_id: task-20260212-001
action: send-email
tool: mcp:email-server/send
status: success
duration_ms: 1200
---

## Action Log

**Input**: Send weekly report to team@example.com
**Output**: Email sent successfully (Message-ID: abc123)
**Approval**: Approved by user at 2026-02-12T14:34:00
```

### 6.3 Audit Trail Integrity

- Log files MUST be append-only. No overwrites, no deletions.
- The orchestrator MUST NOT modify past log entries.
- A daily digest is written to `vault/logs/YYYY-MM-DD_digest.md` summarizing all actions.

---

## 7. Error Handling Philosophy

### 7.1 Principles

1. **Fail loud, not silent.** Every error is logged and surfaced in the dashboard.
2. **Fail safe.** On uncertainty, halt and ask the human. Never guess.
3. **Fail contained.** One task failure MUST NOT cascade to other tasks.
4. **Fail recoverable.** Prefer idempotent actions so retries are safe.

### 7.2 Error Categories

| Category | Response |
|---|---|
| **Config error** (missing env var, bad path) | Log, set task `failed`, alert in dashboard |
| **Network error** (API timeout, 5xx) | Retry once after 30s, then fail |
| **Auth error** (expired token, 401/403) | Fail immediately, flag for human intervention |
| **Validation error** (bad input data) | Fail immediately, log the reason |
| **Unknown error** | Fail immediately, log full context, flag in dashboard |

### 7.3 Error Escalation

```
Error → Log → Update task status → Update dashboard → Wait for human
```

The agent MUST NEVER enter an infinite retry loop or attempt creative workarounds for persistent failures.

---

## 8. Hackathon Deliverable Goals

### 8.1 Bronze MVP — Demo Checklist

These are the minimum deliverables for a successful hackathon demo:

- [ ] **Working watcher**: File watcher detects a new task dropped into `vault/inbox/`
- [ ] **Orchestrator loop**: Claude Code reads the task, generates a plan, writes it to the task file
- [ ] **Approval gate**: Demo the human-in-the-loop approval flow via Obsidian
- [ ] **MCP action**: At least one MCP server executes an approved action (e.g., draft email, create file)
- [ ] **Audit log**: Show the complete audit trail in the vault
- [ ] **Dashboard**: `vault/dashboard.md` shows system status, pending approvals, recent actions
- [ ] **Kill switch**: Demonstrate `HALT.md` stopping the system
- [ ] **3-minute demo**: Smooth end-to-end flow: trigger → plan → approve → execute → log

### 8.2 Demo Scenario

> "The user drops a markdown file into the inbox requesting a weekly status report email. The AI Employee reads it, drafts the email, presents it for approval in Obsidian, and upon approval, sends it via the email MCP server — all logged and auditable."

### 8.3 Stretch Goals (Silver Preview)

- [ ] Multi-step task chains with intermediate checkpoints
- [ ] Obsidian knowledge graph linking tasks, context, and logs
- [ ] Schedule-triggered tasks (daily standup summary)
- [ ] Risk-tiered auto-approval for T0/T1 actions

---

## 9. Constitutional Amendments

This constitution may be amended by:

1. Creating a proposal file in `vault/inbox/` with tag `constitution-amendment`.
2. Documenting the proposed change and rationale.
3. Obtaining explicit human approval.
4. Updating this file with a new version number and date.

Changes to safety rules (Section 4) require extra scrutiny and must never weaken the approval requirements for T4 actions.

---

*This constitution governs the behavior of the Personal AI Employee system. All components — watchers, orchestrator, MCP servers, and vault structure — must comply with these rules. When in doubt, prioritize safety over speed and transparency over cleverness.*
