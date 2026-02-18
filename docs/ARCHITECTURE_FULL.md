# Full System Architecture -- Bronze through Platinum

> **Version:** 4.0.0-platinum
> **Last Updated:** 2026-02-17

---

## Tier Overview

```
BRONZE   Vault system, file watcher, MCP tools, audit logging
SILVER   Web UI, REST API, WebSocket, SQLite database
GOLD     Plugin system, multi-agent reasoning, security layer
PLATINUM Persistent memory, scheduler, monitoring, demo mode
```

---

## Directory Structure

```
Hackathon 0/
|-- api/                    [Silver]  FastAPI REST + WebSocket server
|   |-- server.py           Main app (all endpoints, Gold+Platinum routes)
|   |-- schemas.py          Pydantic models (Silver + Gold + Platinum)
|   +-- websocket.py        WebSocket connection manager
|
|-- gold/                   [Gold]    Advanced automation layer
|   |-- tools/              System tool layer
|   |   |-- base.py         BaseTool, ToolRegistry, ToolExecutor
|   |   |-- filesystem.py   Safe file operations
|   |   |-- email.py        Email drafting/sending (mock safe)
|   |   |-- shell.py        Sandboxed shell commands
|   |   +-- calendar.py     Calendar scheduling
|   |-- agents/             Multi-agent reasoning
|   |   |-- base.py         BaseAgent, AgentContext
|   |   |-- planner.py      PlannerAgent (generates plans)
|   |   |-- executor.py     ExecutorAgent (executes steps)
|   |   |-- reviewer.py     ReviewerAgent (validates results)
|   |   +-- coordinator.py  AgentCoordinator (pipeline orchestration)
|   +-- security/           Security layer
|       +-- permissions.py  PermissionRegistry, Sandbox, RiskTier
|
|-- plugins/                [Gold]    Dynamically loadable plugins
|   |-- base.py             PluginBase, PluginManager
|   |-- email/plugin.py     Email plugin
|   |-- filesystem/plugin.py Filesystem plugin
|   |-- browser/plugin.py   Browser plugin (simulated)
|   +-- calendar/plugin.py  Calendar plugin
|
|-- platinum/               [Platinum] Production-grade features
|   |-- memory/
|   |   +-- memory_store.py Persistent memory (SQLite-backed)
|   |-- scheduler/
|   |   +-- scheduler.py    Task scheduling, background worker, retry
|   +-- monitoring/
|       +-- monitor.py      Metrics, health checks, alerts
|
|-- orchestrator/           [Bronze+Silver] Core orchestration engine
|-- watchers/               [Bronze]  File watcher layer
|-- mcp-servers/            [Bronze]  MCP tool servers (Node.js)
|-- memory/                 [Silver]  SQLite task database
|-- ui/                     [Silver]  Web dashboard (HTML/CSS/JS)
|-- tests/                  Test suites for all tiers (171 tests)
|-- vault/                  Obsidian vault (source of truth)
|
|-- run_silver.py           Silver entry point (uvicorn on port 8000)
+-- run_demo.py             Platinum demo (one-command full stack)
```

---

## Data Flow

```
[User] ---> vault/inbox/ ---> [File Watcher] ---> vault/tasks/
                                                      |
                                                      v
                                              [Orchestrator]
                                                      |
                              +-------+-------+-------+
                              |       |       |       |
                              v       v       v       v
                          [Planner] [Executor] [Reviewer] [Coordinator]
                              |       |                     |
                              v       v                     v
                          [AI Plan] [Tools]            [Verdict]
                                      |
                    +---------+-------+-------+--------+
                    |         |       |       |        |
                    v         v       v       v        v
                [Email]  [Files] [Shell] [Calendar] [Browser]
                    |         |       |       |        |
                    v         v       v       v        v
               [Permission Filter / Sandbox / Risk Tiers]
                              |
                              v
                    [Approval Queue] ---> [Human Approval]
                              |
                              v
                   [Execute & Log Results]
                              |
                              v
                   [Persistent Memory Store]
```

---

## API Endpoints

### Silver Tier
- `GET /` -- Dashboard UI
- `POST /tasks` -- Create task
- `GET /tasks` -- List tasks
- `GET /tasks/{id}` -- Get task
- `POST /approve/{id}` -- Approve task
- `GET /logs/{id}` -- Get logs
- `WebSocket /ws` -- Real-time updates
- `POST /demo/run` -- Demo pipeline

### Gold Tier
- `GET /tools` -- List registered tools
- `POST /tools/execute` -- Execute tool action
- `GET /plugins` -- List loaded plugins
- `GET /approvals` -- Pending action approvals
- `POST /approvals/{id}/approve` -- Approve action
- `POST /approvals/{id}/deny` -- Deny action
- `POST /agents/pipeline` -- Run multi-agent pipeline

### Platinum Tier
- `GET /health` -- Health checks
- `GET /monitoring` -- Full monitoring dashboard
- `GET /alerts` -- System alerts
- `POST /alerts/{id}/acknowledge` -- Acknowledge alert
- `POST /memory/store` -- Store memory
- `POST /memory/recall` -- Recall memories
- `GET /memory/search?q=` -- Search memory
- `GET /memory/stats` -- Memory statistics
- `GET /scheduler/tasks` -- Scheduled tasks
- `GET /scheduler/status` -- Scheduler status

---

## Security Model (Gold Tier)

### Risk Tiers
- **T0** Read-only (auto-approved): read_file, list_files, get_calendar
- **T1** Low risk (auto-approved): draft_email, create_file, schedule_event
- **T2** Medium risk (requires approval): send_email, modify_file, delete_file
- **T3** High risk (requires approval): shell_command, bulk_email
- **T4** Critical (multi-step approval): admin_command, system_config

### Sandbox Constraints
- File operations restricted to vault/ directory
- Shell commands validated against blocklist
- Max file size: 10MB
- Shell timeout: 30 seconds
- Rate limiting per action

---

## Multi-Agent Pipeline (Gold Tier)

```
PlannerAgent --> ExecutorAgent --> ReviewerAgent
     |                |                |
     v                v                v
 Analyze task    Execute steps    Validate results
 Detect tools    Permission check  Check success rate
 Generate plan   Route to tools    Issue verdict
```

Verdicts: `approved` | `partial` | `rejected` | `no_results`

---

## Persistent Memory (Platinum Tier)

SQLite-backed with 4 tables:
- **memories** -- Key-value store with categories, tags, importance
- **task_history** -- Complete task execution records
- **context_entries** -- Context for recall across sessions
- **decisions** -- Recorded decisions with reasoning/outcome

---

## Usage

```bash
# Run the full demo (all tiers)
python run_demo.py

# Start the web server (Silver + Gold + Platinum endpoints)
python run_silver.py

# Run all tests (171 tests)
python -m pytest tests/ -v
```
