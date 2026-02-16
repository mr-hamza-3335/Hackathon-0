# Personal AI Employee — Autonomous Digital FTE

> **Hackathon Entry**: Personal AI Employee Hackathon — Building Autonomous Digital FTEs

A local-first AI agent that plans and executes tasks with full human oversight. Drop a markdown file, the AI plans it, you approve it, MCP servers execute it, everything is logged. No cloud. No vendor lock-in. Complete audit trail.

```
  Drop Task  -->  AI Plans  -->  You Approve  -->  MCP Executes  -->  Everything Logged
      |              |               |                  |                    |
   Watcher        Cohere          Obsidian         MCP Server            Vault
  (Python)       (API/Sim)       (Markdown)        (Node.js)         (Append-Only)
```

---

## What Makes This Special

- **Local-first**: Runs entirely on your machine. No cloud databases, no external APIs required.
- **Human-in-the-loop**: Every action requires explicit human approval before execution.
- **Fully auditable**: Append-only markdown logs capture every state transition, tool call, and outcome.
- **Kill switch**: Create `vault/HALT.md` to stop all automation instantly. Delete it to resume.
- **Obsidian-native**: The vault *is* the UI. View dashboards, approve tasks, and read logs in Obsidian.
- **Upgrade path**: Bronze (MVP) architecture is designed to scale cleanly to Silver and Gold tiers.

---

## 2-Command Setup

```bash
bash install_dependencies.sh   # Install Python + Node.js deps, create .env, run tests
bash run_system.sh             # Start the full system
```

That's it. The system is running.

---

## Cohere API Setup

The AI reasoning layer uses [Cohere](https://cohere.com/) for plan generation. To enable it:

1. Sign up at [dashboard.cohere.com](https://dashboard.cohere.com/)
2. Create an API key
3. Add it to your `.env` file:
   ```
   COHERE_API_KEY=your-key-here
   ```

If `COHERE_API_KEY` is not set, the system runs in **simulation mode** — all orchestration works normally with pre-built demo responses, no API calls are made.

---

## How It Works

1. **You drop a markdown file** into `vault/inbox/`
2. **The file watcher** detects it, validates YAML frontmatter, moves it to `vault/tasks/`
3. **The orchestrator** calls Cohere to generate a step-by-step plan
4. **The plan appears** in `vault/needs_action/` — open it in Obsidian
5. **You review and approve** (move to `vault/approved/` or edit `status: approved`)
6. **MCP servers execute** the approved actions (send emails, create files)
7. **Everything is logged** to `vault/logs/` with timestamps and full audit trail
8. **CEO report auto-generates** in `vault/reports/` with executive summary
9. **The task archives** to `vault/completed/` — done

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PERSONAL AI EMPLOYEE                                  │
│                         Bronze Tier (MVP)                                    │
│                                                                              │
│  ┌──────────────┐   ┌───────────────────┐   ┌────────────────────────────┐  │
│  │  PERCEPTION   │   │   ORCHESTRATION   │   │          ACTION            │  │
│  │               │   │                   │   │                            │  │
│  │  Python       │──>│  Cohere API       │──>│  MCP Servers (Node.js)     │  │
│  │  File Watcher │   │  Reasoning Engine │   │  - demo-server             │  │
│  │               │   │  State Machine    │   │  - email-server            │  │
│  └──────────────┘   └─────────┬─────────┘   └────────────────────────────┘  │
│                               │                                              │
│                      ┌────────┴─────────┐                                   │
│                      │      MEMORY      │                                   │
│                      │  Obsidian Vault  │  <-- Human reviews & approves     │
│                      │  (Markdown)      │      via Obsidian UI              │
│                      └──────────────────┘                                   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    WATCHDOG SUPERVISOR                                │   │
│  │         Process management, health monitoring, auto-restart          │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Four-Layer Architecture

| Layer | Technology | Responsibility |
|-------|-----------|----------------|
| **Perception** | Python + watchdog | Monitor `vault/inbox/` for new task files |
| **Orchestration** | Python + Cohere API | Plan tasks, manage lifecycle, coordinate execution |
| **Memory** | Obsidian vault (markdown) | Dashboard, tasks, logs, context, reports |
| **Action** | Node.js + MCP SDK | Execute approved operations via tool servers |

### Task Lifecycle (9-State Machine)

```
  NEW --> PENDING --> PLANNING --> AWAITING_APPROVAL --> APPROVED --> EXECUTING --> COMPLETED
                        |                  |                             |
                        v                  v                             v
                      FAILED           REJECTED                       FAILED
                        |                                               |
                        '--------> PENDING (retry) <--------------------'
```

### Data Flow

```
  USER                   WATCHER              ORCHESTRATOR           MCP SERVER
   |                       |                       |                      |
   | 1. Drop task.md       |                       |                      |
   |---------------------->|                       |                      |
   |                       | 2. Validate & move    |                      |
   |                       |---------------------->|                      |
   |                       |                       | 3. Cohere plans      |
   |                       |                       |                      |
   | 4. Review plan        |                       |                      |
   |<----------------------------------------------|                      |
   |                       |                       |                      |
   | 5. Approve            |                       |                      |
   |---------------------------------------------->|                      |
   |                       |                       | 6. Execute via MCP   |
   |                       |                       |--------------------->|
   |                       |                       | 7. Result + log      |
   |                       |                       |<---------------------|
   | 8. See results        |                       |                      |
   |<----------------------------------------------|                      |
```

---

## Project Structure

```
├── vault/                          # Obsidian vault (open in Obsidian)
│   ├── inbox/                      # Drop new tasks here
│   ├── needs_action/               # AI-planned tasks awaiting approval
│   ├── approved/                   # Move tasks here to approve
│   ├── completed/                  # Finished tasks with audit trail
│   ├── tasks/                      # Orchestrator working directory
│   │   └── archive/                # Archived completed tasks
│   ├── logs/                       # Append-only structured audit logs
│   ├── drafts/                     # Email drafts generated by MCP
│   ├── reports/                    # CEO briefing reports
│   ├── context/                    # User profile, tools registry
│   └── dashboard.md                # Live system status
│
├── watchers/                       # Perception layer
│   ├── file_watcher.py             # Monitors inbox for new tasks
│   └── utils/markdown_parser.py    # YAML frontmatter parser
│
├── orchestrator/                   # Orchestration layer
│   ├── orchestrator.py             # Unified orchestrator engine
│   ├── task_manager.py             # 9-state task lifecycle machine
│   ├── approval_gate.py            # Human approval polling
│   ├── ai_bridge.py                # Cohere API integration + simulation
│   ├── action_dispatcher.py        # MCP tool routing and execution
│   ├── reporter.py                 # CEO briefing report generator
│   ├── dashboard.py                # Dashboard auto-updater
│   ├── logger.py                   # Structured audit logging
│   ├── config.py                   # Configuration loader
│   └── prompts/                    # AI prompt templates
│
├── supervisor/                     # Process supervisor
│   └── watchdog.py                 # Manages all process lifecycles
│
├── mcp-servers/                    # Action layer (MCP servers)
│   ├── demo-server/                # Core MCP server
│   │   ├── index.js                # MCP protocol handler
│   │   └── tools/                  # draft_email, create_file
│   └── email-server/               # Email MCP server
│       └── server.js               # send_email tool
│
├── tests/                          # 43 pytest tests
├── docs/                           # Constitution, spec, architecture
├── e2e_demo_test.py                # Automated end-to-end demo test
│
├── install_dependencies.sh         # One-command setup
├── run_system.sh                   # One-command start
└── requirements.txt                # Python dependencies
```

---

## Commands

| Command | Description |
|---------|-------------|
| `bash install_dependencies.sh` | Install all dependencies, create `.env`, verify with tests |
| `bash run_system.sh` | Start supervisor + watcher + orchestrator |
| `bash run_system.sh --stop` | Stop all running components |
| `bash run_system.sh --status` | Check system state and vault counts |
| `bash run_system.sh --demo` | Start system + trigger a demo task |
| `bash run_system.sh --test` | Run integration test cycle |
| `python -m orchestrator.reporter` | Generate CEO briefing report |
| `python e2e_demo_test.py` | Run automated end-to-end demo test |
| `python -m pytest tests/ -v` | Run full test suite (43 tests) |

---

## MCP Tool Servers

### demo-server (Core Tools)

| Tool | Description | Risk Tier |
|------|-------------|-----------|
| `draft_email` | Save email draft to `vault/drafts/` | T3 — Approval required |
| `create_file` | Create file on local filesystem | T1 — Approval required (Bronze) |

### email-server (Email Operations)

| Tool | Description | Risk Tier |
|------|-------------|-----------|
| `send_email` | Compose and send email (simulated in Bronze) | T3 — Approval required |

---

## Approval Methods

### Method 1: Folder Move (Recommended for Demo)

```
vault/needs_action/my-task.md  -->  vault/approved/my-task.md
```

Drag the file. The orchestrator detects it and executes.

### Method 2: Frontmatter Edit (Obsidian-Native)

Open the task file and change `status: awaiting-approval` to `status: approved`.

---

## Task File Format

```markdown
---
id: task-20260215-001
status: new
priority: high
source: manual
tags: [email, weekly-report]
approval_required: true
created: 2026-02-15T10:00:00
---

## Request

What you want the AI Employee to do.

## Context

Any background information or constraints.
```

Drop this into `vault/inbox/` and the system handles the rest.

---

## CEO Briefing Reporter

After each task completes, the system automatically generates an executive summary report:

```bash
python -m orchestrator.reporter    # Generate manually
```

Reports are saved to `vault/reports/weekly_report.md` and include:
- Executive summary paragraph
- Task completion metrics
- Tool usage breakdown
- Recent actions table
- Completed tasks overview

---

## Demo Walkthrough (3 Minutes)

### Setup
```bash
bash install_dependencies.sh    # Once
bash run_system.sh --demo       # Start + trigger demo
```

### What Happens
1. **[0:00]** System starts, demo task drops into inbox
2. **[0:15]** Watcher detects it, validates, moves to tasks
3. **[0:30]** Cohere generates a plan with actionable steps
4. **[0:45]** Plan appears in `vault/needs_action/`
5. **[1:00]** You move it to `vault/approved/`
6. **[1:15]** MCP server sends email, saves draft to `vault/drafts/`
7. **[1:30]** Task completes, CEO report auto-generates
8. **[1:45]** Dashboard and audit logs updated
9. **[2:00]** Show audit trail in `vault/logs/`
10. **[2:30]** Demo kill switch: create `vault/HALT.md`
11. **[3:00]** *"Local-first. Human-in-the-loop. Fully auditable."*

### Automated Demo Test
```bash
python e2e_demo_test.py    # Runs full lifecycle — all 26 checks pass
```

### Key Talking Points
- Everything runs locally — no cloud databases, no external services
- Human approves every action before execution
- Complete audit trail in plain markdown
- Kill switch stops everything instantly
- Obsidian-native — no custom UI needed
- Bronze -> Silver upgrade path designed in from day one

---

## Safety Mechanisms

### Risk Tiers

| Tier | Risk | Example | Approval |
|------|------|---------|----------|
| T0 | None | Read vault files | Auto |
| T1 | Low | Write to vault | Auto (Bronze: required) |
| T2 | Medium | Fetch email subjects | Required |
| T3 | High | Send email | Required |
| T4 | Critical | Delete files | Always required |

### Kill Switch

Create `vault/HALT.md` to **immediately stop all automation**. The orchestrator and supervisor check for this file every poll cycle. Delete the file to resume.

### Append-Only Audit Logs

Every action produces a structured markdown log in `vault/logs/` with:
- ISO 8601 timestamp
- Task ID and action description
- Tool used and execution duration
- Success/failure status with error details

Logs are never overwritten or deleted. Each log has YAML frontmatter for machine parsing.

### Human Approval Gate

No external action executes without explicit human approval. The orchestrator generates a plan, presents it for review, and waits indefinitely until the human approves or rejects.

---

## Bronze vs Silver Capabilities

| Capability | Bronze (Current) | Silver (Planned) |
|-----------|-------------------|-------------------|
| Task input | Manual file drop | Email/calendar triggers |
| AI reasoning | Cohere API (or simulation) | Cohere API with structured output |
| Email | Draft + simulated send | Gmail API integration |
| Approval | File move / frontmatter edit | Obsidian plugin with buttons |
| Concurrency | Single task at a time | Parallel task processing |
| Reporting | Auto-generated markdown | Scheduled weekly reports |
| Context | Static user profile | Learning preferences over time |
| MCP servers | 2 demo servers | Production tool ecosystem |

---

## Documentation

| Document | Description |
|----------|-------------|
| [CONSTITUTION.md](docs/CONSTITUTION.md) | System rules, safety tiers, coding standards |
| [SPECIFICATION.md](docs/SPECIFICATION.md) | Full system design and component responsibilities |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Visual diagrams, data flow, security boundaries |
| [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Sprint plan, risks, Silver roadmap |
| [DEMO-SCRIPT.md](docs/DEMO-SCRIPT.md) | 3-minute hackathon demo runbook |

---

## Tech Stack

| Technology | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11+ | Watchers, orchestrator, task management |
| Node.js | 20+ | MCP action servers |
| Cohere SDK | 5.0+ | AI reasoning via Cohere API (with simulation fallback) |
| Obsidian | 1.5+ | Human interface and dashboard |
| watchdog | 4.0+ | Filesystem monitoring |
| MCP SDK | 1.0+ | Model Context Protocol for tool execution |
| PyYAML | 6.0+ | YAML frontmatter parsing |
| pytest | 8.0+ | Test framework (43 tests, all passing) |

---

## License

MIT

---

*Built for the Personal AI Employee Hackathon — Building Autonomous Digital FTEs*
*Local-first. Human-in-the-loop. Fully auditable.*
