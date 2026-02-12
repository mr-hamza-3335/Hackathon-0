# SPECIFICATION.md — Bronze-Tier Personal AI Employee

> **Version:** 1.0.0-bronze
> **Governs:** [CONSTITUTION.md](./CONSTITUTION.md)
> **Last Updated:** 2026-02-12

---

## 1. Full Project Directory Tree

```
hackathon-0/
│
├── docs/
│   ├── CONSTITUTION.md              # System rules and constraints
│   ├── SPECIFICATION.md             # This file — full system design
│   ├── ARCHITECTURE.md              # Visual architecture and data flow
│   └── DEMO-SCRIPT.md              # Hackathon demo runbook
│
├── setup/
│   └── init_project.sh              # One-command project scaffolding
│
├── vault/                           # Obsidian vault root (open this in Obsidian)
│   ├── .obsidian/                   # Obsidian config (auto-generated)
│   ├── inbox/                       # Drop zone — new task triggers land here
│   │   └── _template.md             # Task template for manual creation
│   ├── tasks/                       # Active task files (moved from inbox)
│   │   └── archive/                 # Completed/failed tasks
│   ├── logs/                        # Append-only audit trail
│   │   └── _log-template.md         # Log entry template
│   ├── context/                     # Long-term memory and preferences
│   │   ├── user-profile.md          # User info, preferences, style
│   │   └── tools-registry.md        # Available MCP tools and capabilities
│   ├── dashboard.md                 # Live system status (Obsidian home page)
│   └── HALT.md.disabled             # Rename to HALT.md to kill the system
│
├── watchers/                        # Python perception layer
│   ├── __init__.py
│   ├── file_watcher.py              # Monitors vault/inbox/ for new files
│   ├── config.py                    # Watcher configuration loader
│   └── utils/
│       ├── __init__.py
│       └── markdown_parser.py       # Parse YAML frontmatter from task files
│
├── orchestrator/                    # Claude Code reasoning layer
│   ├── __init__.py
│   ├── run.py                       # Main loop — poll, reason, propose, execute
│   ├── claude_bridge.py             # Interface to Claude Code CLI
│   ├── task_manager.py              # Task lifecycle state machine
│   ├── approval_gate.py             # Human-in-the-loop approval checker
│   ├── action_dispatcher.py         # Route approved actions to MCP servers
│   ├── logger.py                    # Structured logging to vault/logs/
│   ├── config.py                    # Orchestrator configuration
│   └── prompts/
│       ├── system.md                # System prompt for Claude reasoning
│       ├── plan_task.md             # Prompt template: generate a plan
│       └── review_result.md         # Prompt template: verify action result
│
├── mcp-servers/                     # MCP action layer (Node.js)
│   ├── demo-server/                 # Minimal demo MCP server
│   │   ├── package.json
│   │   ├── index.js                 # Server entry point
│   │   └── tools/
│   │       ├── draft_email.js       # Tool: draft an email to vault
│   │       └── create_file.js       # Tool: create a file on disk
│   └── README.md
│
├── tests/
│   ├── test_file_watcher.py
│   ├── test_task_manager.py
│   ├── test_approval_gate.py
│   └── test_markdown_parser.py
│
├── .env.example                     # Template: required environment variables
├── .gitignore
├── requirements.txt                 # Python deps (watchdog, pyyaml, etc.)
├── package.json                     # Root Node deps (if needed)
└── README.md
```

---

## 2. Component Responsibilities

### 2.1 Watchers (Perception Layer)

| Component | File | Responsibility |
|---|---|---|
| **File Watcher** | `watchers/file_watcher.py` | Monitors `vault/inbox/` using `watchdog`. When a new `.md` file appears, validates its frontmatter and notifies the orchestrator by writing a trigger signal. |
| **Config** | `watchers/config.py` | Loads watcher settings from environment and `orchestrator/config.yaml`. Defines poll intervals, watched paths, and file patterns. |
| **Markdown Parser** | `watchers/utils/markdown_parser.py` | Extracts YAML frontmatter and body from markdown files. Validates required fields (`id`, `status`, `priority`). |

**Watcher Contract:**
- Input: Filesystem events in `vault/inbox/`
- Output: Validated task file moved to `vault/tasks/` with `status: pending`
- Side effects: None outside the vault
- Trigger mechanism: Writes a `.trigger` file to `vault/tasks/` that the orchestrator polls

### 2.2 Orchestrator (Reasoning Layer)

| Component | File | Responsibility |
|---|---|---|
| **Main Loop** | `orchestrator/run.py` | Entry point. Runs a poll loop: scan for pending tasks → reason → propose → wait for approval → execute → log. |
| **Claude Bridge** | `orchestrator/claude_bridge.py` | Shells out to `claude` CLI with structured prompts. Parses Claude's response into actionable plans. |
| **Task Manager** | `orchestrator/task_manager.py` | State machine for task lifecycle. Reads/writes task frontmatter. Enforces valid state transitions. |
| **Approval Gate** | `orchestrator/approval_gate.py` | Polls task files for `status: approved`. Blocks execution until human approval is granted. Respects `HALT.md`. |
| **Action Dispatcher** | `orchestrator/action_dispatcher.py` | Maps approved plan steps to MCP tool calls. Sends requests to MCP servers. Captures responses. |
| **Logger** | `orchestrator/logger.py` | Writes structured log entries to `vault/logs/` as markdown with YAML frontmatter. |

**Orchestrator Contract:**
- Input: Task files in `vault/tasks/` with `status: pending`
- Output: Executed actions, updated task status, audit logs
- Constraints: MUST check `HALT.md` before every action. MUST wait for approval on T2+ actions.

### 2.3 Vault (Memory Layer)

| Directory | Purpose |
|---|---|
| `vault/inbox/` | Drop zone. Users or watchers place new task requests here. |
| `vault/tasks/` | Active workspace. Orchestrator reads and updates tasks here. |
| `vault/tasks/archive/` | Completed or failed tasks moved here for history. |
| `vault/logs/` | Immutable audit trail. One file per action. |
| `vault/context/` | Persistent memory. User preferences, tool docs, learned patterns. |
| `vault/dashboard.md` | Auto-updated status page. Obsidian home screen. |

**Vault Contract:**
- The vault is a **passive data store**. It does not execute logic.
- All vault files are valid markdown with YAML frontmatter.
- The vault can be opened in Obsidian at any time without disrupting the system.

### 2.4 MCP Servers (Action Layer)

| Server | Tools | Purpose |
|---|---|---|
| `demo-server` | `draft_email`, `create_file` | Minimal demo actions for hackathon |

**MCP Contract:**
- Each tool receives a JSON input, returns a JSON output.
- Tools MUST validate inputs before executing.
- Tools MUST NOT access the vault directly — only the orchestrator reads/writes the vault.
- Tools MUST return structured results (not raw HTML or stack traces).

---

## 3. Step-by-Step System Behavior

### Phase 1: Trigger

```
1. User drops a markdown file into vault/inbox/
   Example: vault/inbox/2026-02-12_send-weekly-report.md

2. File contains:
   ---
   id: task-20260212-001
   status: new
   priority: high
   source: manual
   tags: [email, weekly-report]
   ---
   ## Request
   Draft and send the weekly status report to team@example.com.
   Include progress on Project Alpha and blockers.
```

### Phase 2: Perceive

```
3. file_watcher.py detects the new file via watchdog
4. Validates frontmatter (required fields present)
5. Sets status: pending
6. Moves file to vault/tasks/2026-02-12_send-weekly-report.md
7. Writes vault/tasks/.trigger with the task ID
```

### Phase 3: Plan

```
8.  run.py poll loop detects .trigger file
9.  Reads the task file
10. Loads context from vault/context/ (user profile, tool registry)
11. Calls Claude via claude_bridge.py with:
    - System prompt (prompts/system.md)
    - Task content
    - Available tools
    - Planning prompt (prompts/plan_task.md)
12. Claude returns a structured plan:
    Step 1: Read recent project notes for progress data
    Step 2: Draft email body
    Step 3: Call mcp:demo-server/draft_email
```

### Phase 4: Propose

```
13. task_manager.py writes the plan into the task file:
    ## Proposed Plan
    - [x] Read context from vault
    - [ ] Draft email with subject "Weekly Report — Feb 12"
    - [ ] Send via email MCP tool (requires approval)

    ## Draft Output
    Subject: Weekly Status Report — Feb 12, 2026
    To: team@example.com
    Body: [AI-generated draft here]

14. Sets status: awaiting-approval
15. dashboard.md is updated to show pending approval
```

### Phase 5: Approve

```
16. User opens Obsidian, sees dashboard notification
17. Opens the task file, reviews the draft
18. Edits frontmatter: status: approved
    (or status: rejected with a ## Rejection Reason)
```

### Phase 6: Execute

```
19. approval_gate.py detects status change to "approved"
20. Checks HALT.md does not exist
21. action_dispatcher.py calls mcp:demo-server/draft_email
22. MCP server processes the request, returns result
```

### Phase 7: Log

```
23. logger.py creates vault/logs/2026-02-12_14-35_email-drafted.md
    Contains: timestamp, task_id, action, tool, input/output, status, duration
24. Task file updated: status: completed
25. Task moved to vault/tasks/archive/
26. dashboard.md updated to reflect completion
```

### Phase 8: Verify

```
27. Orchestrator calls Claude with review_result.md prompt
28. Claude confirms action completed successfully
29. If verification fails → status: failed, logged, dashboard alerted
```

---

## 4. Demo Scenario — Hackathon Presentation

### Setup (Before Demo)

1. Open terminal with the project running (`python -m orchestrator.run`)
2. Open Obsidian with the vault visible (dashboard.md as home)
3. Have a split-screen: terminal left, Obsidian right

### Live Demo Script (3 minutes)

**[0:00–0:30] Introduction**
> "This is an AI Employee — a local-first autonomous agent that plans and executes tasks with human oversight."

**[0:30–1:00] Trigger**
> "I drop a task into the inbox..."
- Drag `send-weekly-report.md` into `vault/inbox/`
- Show the file watcher detecting it in the terminal
- Show it appear in `vault/tasks/` in Obsidian

**[1:00–1:45] AI Reasoning**
> "The AI Employee reads the task, loads context, and generates a plan..."
- Show Claude processing in the terminal
- Switch to Obsidian: the task file now has a `## Proposed Plan` and `## Draft Output`
- Show `dashboard.md` flagging "1 action awaiting approval"

**[1:45–2:15] Human Approval**
> "Nothing happens without my say-so. I review the draft and approve it."
- Edit the frontmatter in Obsidian: `status: approved`
- Show the orchestrator detecting the approval in the terminal

**[2:15–2:45] Execution**
> "The approved action executes through a Model Context Protocol server."
- Show MCP tool call in terminal
- Show success response
- Switch to Obsidian: task is now `status: completed`, moved to archive

**[2:45–3:00] Audit Trail**
> "Everything is logged. Every action, every approval, fully auditable."
- Open `vault/logs/` — show the log entry
- Open `dashboard.md` — show the clean status
- Quick flash: show `HALT.md` kill switch concept

### Demo Kill Switch Bonus

> "And if anything goes wrong..."
- Create `vault/HALT.md`
- Show the orchestrator immediately stop
- Delete `HALT.md`, show it resume

---

## 5. Configuration Defaults

### orchestrator/config.yaml

```yaml
vault:
  root: ./vault
  inbox: ./vault/inbox
  tasks: ./vault/tasks
  logs: ./vault/logs
  context: ./vault/context
  halt_file: ./vault/HALT.md

orchestrator:
  poll_interval_seconds: 3
  max_retries: 1
  retry_delay_seconds: 30
  max_actions_per_hour: 10

claude:
  model: claude-opus-4-6
  max_tokens: 4096
  temperature: 0.3

mcp:
  servers:
    demo:
      command: node
      args: ["./mcp-servers/demo-server/index.js"]

approval:
  require_for_tiers: [T2, T3, T4]
  poll_interval_seconds: 2
  timeout_minutes: 60
```

### .env.example

```bash
# Claude API
ANTHROPIC_API_KEY=sk-ant-xxxxx

# MCP Server Config
MCP_DEMO_PORT=3100

# Vault Path (override default)
# VAULT_ROOT=./vault

# Logging
LOG_LEVEL=INFO
```

---

## 6. State Machine — Task Lifecycle

```
                    ┌──────────────┐
                    │     new      │  (dropped in inbox)
                    └──────┬───────┘
                           │ watcher validates
                           ▼
                    ┌──────────────┐
                    │   pending    │  (in vault/tasks/)
                    └──────┬───────┘
                           │ orchestrator plans
                           ▼
                    ┌──────────────┐
                    │ in-progress  │  (Claude reasoning)
                    └──────┬───────┘
                           │ plan written to file
                           ▼
               ┌───────────────────────┐
               │  awaiting-approval    │  (human reviews)
               └─────┬──────────┬─────┘
                     │          │
            approved │          │ rejected
                     ▼          ▼
              ┌───────────┐  ┌──────────┐
              │ executing  │  │ rejected │ → archive
              └─────┬──────┘  └──────────┘
                    │
           ┌───────┴────────┐
           │                │
      success          failure
           │                │
           ▼                ▼
    ┌────────────┐   ┌──────────┐
    │ completed  │   │  failed  │ → dashboard alert
    └─────┬──────┘   └────┬─────┘
          │               │
          ▼               ▼
       archive         archive
```

---

*This specification defines every component, behavior, and flow for the Bronze-tier Personal AI Employee. Build to this spec, demo to this script, iterate to Silver.*
