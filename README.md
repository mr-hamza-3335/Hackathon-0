# Personal AI Employee — Autonomous Digital FTE

A local-first AI agent that plans and executes tasks with human oversight.
Built for the **Personal AI Employee Hackathon: Building Autonomous Digital FTEs**.

```
  Drop Task → AI Plans → You Approve → MCP Executes → Everything Logged
      ↑           ↑           ↑              ↑               ↑
   Watcher     Claude     Obsidian      MCP Server        Vault
```

---

## 2-Command Setup

```bash
bash install_dependencies.sh
bash run_system.sh
```

That's it. The system is running.

---

## What It Does

1. **You drop a markdown file** into `vault/inbox/`
2. **The file watcher** detects it, validates it, moves it to `vault/tasks/`
3. **The orchestrator** calls Claude to generate a step-by-step plan
4. **The plan appears** in `vault/needs_action/` — open it in Obsidian
5. **You review and approve** (move to `vault/approved/` or edit frontmatter)
6. **The MCP server executes** the approved action (drafts emails, creates files)
7. **Everything is logged** to `vault/logs/` with timestamps and audit trail
8. **The task moves** to `vault/completed/` — done

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ┌───────────┐  ┌──────────────────┐  ┌───────────────────────┐ │
│  │ PERCEPTION │  │  ORCHESTRATION   │  │       ACTION          │ │
│  │            │  │                  │  │                       │ │
│  │  Python    │─→│  Claude Code     │─→│  MCP Server           │ │
│  │  Watchers  │  │  Reasoning       │  │  (Node.js)            │ │
│  └───────────┘  └────────┬─────────┘  └───────────────────────┘ │
│                          │                                       │
│                 ┌────────┴─────────┐                            │
│                 │      MEMORY      │                            │
│                 │  Obsidian Vault  │ ← You review + approve     │
│                 └──────────────────┘                            │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  WATCHDOG SUPERVISOR                       │  │
│  │          Manages all processes, health checks              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

| Layer | Technology | Role |
|---|---|---|
| Perception | Python + watchdog | Detect new tasks in `vault/inbox/` |
| Orchestration | Python + Claude CLI | Plan, reason, coordinate actions |
| Memory | Obsidian vault (markdown) | Dashboard, tasks, logs, context |
| Action | Node.js + MCP SDK | Execute approved operations |
| Supervisor | Python watchdog module | Process management, health checks |

---

## Project Structure

```
├── vault/                       # Obsidian vault — open this in Obsidian
│   ├── inbox/                   # Drop new tasks here
│   ├── needs_action/            # AI-planned tasks awaiting your approval
│   ├── approved/                # Move tasks here to approve
│   ├── completed/               # Finished tasks with audit trail
│   ├── tasks/                   # Orchestrator working directory
│   ├── logs/                    # Append-only audit logs
│   ├── context/                 # User profile, tools registry
│   ├── dashboard.md             # Live system status
│   └── Company_Handbook.md      # AI Employee reference guide
│
├── watchers/                    # File watcher (perception layer)
│   ├── file_watcher.py          # Monitors inbox for new tasks
│   └── utils/markdown_parser.py # YAML frontmatter parser
│
├── orchestrator/                # AI reasoning engine
│   ├── orchestrator.py          # Unified entry point
│   ├── run.py                   # Modular entry point
│   ├── task_manager.py          # 9-state task lifecycle
│   ├── approval_gate.py         # Human approval polling
│   ├── claude_bridge.py         # Claude CLI integration
│   ├── action_dispatcher.py     # MCP tool routing
│   ├── dashboard.py             # Dashboard auto-updater
│   ├── logger.py                # Structured audit logging
│   └── prompts/                 # AI prompt templates
│
├── supervisor/                  # Process supervisor
│   └── watchdog.py              # Manages watcher + orchestrator lifecycle
│
├── mcp-servers/demo-server/     # MCP action server (Node.js)
│   ├── index.js                 # MCP protocol handler
│   └── tools/                   # draft_email, create_file
│
├── tests/                       # 43 pytest tests (all passing)
├── docs/                        # Constitution, spec, architecture, plans
│
├── install_dependencies.sh      # One-command setup
├── run_system.sh                # One-command start
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

---

## Commands

| Command | What It Does |
|---|---|
| `bash install_dependencies.sh` | Install Python + Node deps, create .env, run tests |
| `bash run_system.sh` | Start the full system (supervisor + watcher + orchestrator) |
| `bash run_system.sh --stop` | Stop all running components |
| `bash run_system.sh --status` | Check what's running and vault state |
| `bash run_system.sh --demo` | Start system + auto-trigger a demo task |
| `bash run_system.sh --test` | Run a quick integration test |

---

## Approval Methods

### Method 1: Folder Move (Recommended for Demo)

```
vault/needs_action/my-task.md  →  vault/approved/my-task.md
```

Just drag the file. The orchestrator detects it and executes.

### Method 2: Frontmatter Edit (Obsidian-Native)

Open the task file and change:
```yaml
status: awaiting-approval
```
to:
```yaml
status: approved
```

---

## Task File Format

```markdown
---
id: task-20260212-001
status: new
priority: high
source: manual
tags: [email, weekly-report]
approval_required: true
---

## Request

What you want the AI Employee to do.

## Context

Any background information.
```

Drop this into `vault/inbox/` and the system handles the rest.

---

## Demo Walkthrough (3 Minutes)

### Setup
```bash
bash install_dependencies.sh    # Once
bash run_system.sh --demo       # Start + trigger demo
```

### What Happens
1. **[0:00]** System starts, demo task drops into inbox
2. **[0:15]** Watcher detects it, moves to tasks
3. **[0:30]** Claude generates a plan with email draft
4. **[0:45]** Plan appears in `vault/needs_action/`
5. **[1:00]** You move it to `vault/approved/`
6. **[1:15]** MCP server drafts the email to `vault/drafts/`
7. **[1:30]** Task moves to `vault/completed/` with full results
8. **[1:45]** Dashboard and logs updated
9. **[2:00]** Show audit trail in `vault/logs/`
10. **[2:30]** Demo kill switch: create `vault/HALT.md`
11. **[3:00]** "Local-first. Human-in-the-loop. Fully auditable."

### Key Talking Points
- Everything runs locally — no cloud databases
- Human approves every action before execution
- Complete audit trail in markdown
- Kill switch stops everything instantly
- Obsidian-native — no custom UI needed
- Bronze → Silver upgrade path designed in

---

## Safety

| Tier | Risk | Example | Approval |
|---|---|---|---|
| T0 | None | Read vault files | Auto |
| T1 | Low | Write to vault | Auto |
| T2 | Low | Fetch email subjects | Required |
| T3 | High | Send email | Required |
| T4 | Critical | Delete files | Always Required |

**Kill Switch:** Create `vault/HALT.md` to stop all automation instantly.

---

## Documentation

| Document | Description |
|---|---|
| [CONSTITUTION.md](docs/CONSTITUTION.md) | System rules, safety tiers, coding standards |
| [SPECIFICATION.md](docs/SPECIFICATION.md) | Full system design, component responsibilities |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Visual diagrams, data flow, security boundaries |
| [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Sprint plan, risks, Silver roadmap |
| [DEMO-SCRIPT.md](docs/DEMO-SCRIPT.md) | 3-minute hackathon demo runbook |
| [TASKS.md](docs/TASKS.md) | 26 implementation tasks (all complete) |

---

## Tech Stack

- **Python 3.11+** — Watchers, orchestrator, task management
- **Node.js 20+** — MCP server with tool handlers
- **Claude Code CLI** — AI reasoning (with simulation fallback)
- **Obsidian** — Human interface and dashboard
- **watchdog** — Filesystem monitoring
- **MCP SDK** — Model Context Protocol for tool execution
- **pytest** — 43 tests, all passing

---

## License

MIT

---

*Built for the Personal AI Employee Hackathon — Building Autonomous Digital FTEs*
