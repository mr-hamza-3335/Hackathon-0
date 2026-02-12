# Personal AI Employee — Bronze MVP

A local-first autonomous AI agent that plans and executes tasks with human oversight. Built for the **Personal AI Employee Hackathon: Building Autonomous Digital FTEs**.

```
  Trigger → Plan → Approve → Execute → Log
     ↑         ↑        ↑         ↑       ↑
  Watcher   Claude   Obsidian    MCP    Vault
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
cd mcp-servers/demo-server && npm install && cd ../..

# 2. Configure environment
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# 3. Start the orchestrator
python -m orchestrator.run

# 4. Start the file watcher (new terminal)
python -m watchers.file_watcher

# 5. Drop a task into the inbox
cp vault/inbox/_demo-task.md vault/inbox/2026-02-12_my-task.md

# 6. Approve in Obsidian
# Open vault/tasks/ → edit status to "approved"
```

## Architecture

```
┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  PERCEPTION  │    │  ORCHESTRATION   │    │      ACTION      │
│  Python      │───→│  Claude Code     │───→│  MCP Servers     │
│  Watchers    │    │  Reasoning       │    │  (Node.js)       │
└─────────────┘    └────────┬─────────┘    └──────────────────┘
                            │
                   ┌────────┴─────────┐
                   │      MEMORY      │
                   │  Obsidian Vault  │ ← Human reviews here
                   └──────────────────┘
```

**Four layers, strict boundaries:**

| Layer | Tech | Role |
|---|---|---|
| Perception | Python + watchdog | Detect new tasks in `vault/inbox/` |
| Orchestration | Python + Claude CLI | Plan, reason, coordinate |
| Memory | Obsidian (markdown) | Dashboard, tasks, logs, context |
| Action | Node.js + MCP SDK | Execute approved operations |

## How It Works

1. **Drop a task** into `vault/inbox/` (markdown with YAML frontmatter)
2. **Watcher detects** the file, validates it, moves to `vault/tasks/`
3. **Orchestrator picks it up**, calls Claude to generate a plan
4. **Plan is written** to the task file with a draft output
5. **Human reviews** in Obsidian and sets `status: approved`
6. **MCP server executes** the approved action (e.g., draft email)
7. **Everything is logged** to `vault/logs/` with full audit trail
8. **Task is archived** and dashboard is updated

## Key Features

- **Local-first**: All data on disk, no cloud databases
- **Human-in-the-loop**: Every external action requires approval (Bronze tier)
- **Auditable**: Append-only markdown logs for every action
- **Kill switch**: Create `vault/HALT.md` to stop everything instantly
- **Obsidian-native**: Dashboard, tasks, and logs viewable in Obsidian
- **MCP-powered**: Real tool execution via Model Context Protocol

## Project Structure

```
├── docs/                  # Constitution, spec, architecture, demo script
├── vault/                 # Obsidian vault (memory + dashboard)
│   ├── inbox/             # Drop tasks here
│   ├── tasks/             # Active tasks (orchestrator reads these)
│   ├── logs/              # Audit trail
│   └── dashboard.md       # Live system status
├── watchers/              # Python file watcher
├── orchestrator/          # Main engine (8 modules)
├── mcp-servers/           # Node.js MCP demo server
│   └── demo-server/       # draft_email + create_file tools
└── tests/                 # pytest test suite
```

## Demo (3 Minutes)

See [`docs/DEMO-SCRIPT.md`](docs/DEMO-SCRIPT.md) for the full timed runbook.

**Quick version:**
1. Start orchestrator + watcher
2. Drop task into inbox
3. Watch AI generate a plan
4. Approve in Obsidian
5. See MCP execute the action
6. Check audit logs

## Documentation

| Document | Description |
|---|---|
| [CONSTITUTION.md](docs/CONSTITUTION.md) | System rules, safety tiers, coding standards |
| [SPECIFICATION.md](docs/SPECIFICATION.md) | Full system design, component responsibilities |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Visual diagrams, data flow, security boundaries |
| [DEMO-SCRIPT.md](docs/DEMO-SCRIPT.md) | 3-minute hackathon demo runbook |
| [TASKS.md](docs/TASKS.md) | Implementation task breakdown (26 tasks, 4 phases) |

## Tech Stack

- **Python 3.11+** — Watchers, orchestrator, task management
- **Node.js 20+** — MCP server with tool handlers
- **Claude Code CLI** — AI reasoning engine
- **Obsidian** — Human interface and dashboard
- **watchdog** — Filesystem monitoring
- **MCP SDK** — Model Context Protocol for tool execution

## Safety

- **T0 (Read vault)**: No approval needed
- **T1 (Write vault)**: No approval needed
- **T2 (External read)**: Approval required
- **T3 (External write)**: Approval required
- **T4 (Destructive)**: Always requires approval

Kill switch: `vault/HALT.md` — create to halt, delete to resume.

## Bronze → Silver Upgrade Path

| Feature | Bronze (Now) | Silver (Next) |
|---|---|---|
| Tasks | Single-step, all approved | Multi-step chains |
| Memory | Flat markdown | Obsidian knowledge graph |
| Perception | File watcher | Webhooks, email, calendar |
| Actions | 2 demo tools | Full MCP tool registry |
| Safety | Approve everything | Risk-tiered auto-approve |

## License

MIT

---

*Built for the Personal AI Employee Hackathon — Building Autonomous Digital FTEs*
