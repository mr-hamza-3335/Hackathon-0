# ARCHITECTURE.md — System Architecture & Data Flow

> **Version:** 1.0.0-bronze
> **Governs:** [CONSTITUTION.md](./CONSTITUTION.md) | [SPECIFICATION.md](./SPECIFICATION.md)
> **Last Updated:** 2026-02-12

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PERSONAL AI EMPLOYEE                            │
│                         Bronze Tier (MVP)                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌──────────────────┐    ┌───────────────────────┐  │
│  │  PERCEPTION  │    │  ORCHESTRATION   │    │       ACTION          │  │
│  │             │    │                  │    │                       │  │
│  │  Python      │───▶│  Claude Code     │───▶│  MCP Servers          │  │
│  │  Watchers    │    │  Reasoning       │    │  (Node.js)            │  │
│  │             │    │  Engine          │    │                       │  │
│  └─────────────┘    └────────┬─────────┘    └───────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│                    ┌──────────────────┐                                 │
│                    │     MEMORY       │                                 │
│                    │                  │                                 │
│                    │  Obsidian Vault  │ ◀── Human reviews & approves   │
│                    │  (Markdown)      │     via Obsidian UI            │
│                    │                  │                                 │
│                    └──────────────────┘                                 │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Component Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          WATCHERS                                    │
│                                                                      │
│  file_watcher.py                                                     │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  watchdog.Observer                                             │  │
│  │       │                                                        │  │
│  │       ▼                                                        │  │
│  │  on_created(event)                                             │  │
│  │       │                                                        │  │
│  │       ▼                                                        │  │
│  │  markdown_parser.parse(file)                                   │  │
│  │       │                                                        │  │
│  │       ├── valid? ──▶ move to vault/tasks/ + write .trigger     │  │
│  │       │                                                        │  │
│  │       └── invalid? ──▶ log warning, leave in inbox             │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
                                │
                          .trigger file
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                                  │
│                                                                      │
│  run.py (main loop)                                                  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                                                                │  │
│  │  while True:                                                   │  │
│  │    ├── check HALT.md ──▶ if exists: sleep & continue          │  │
│  │    ├── scan for .trigger files                                 │  │
│  │    ├── task_manager.load(task_file)                            │  │
│  │    │                                                           │  │
│  │    ├── PLAN PHASE                                              │  │
│  │    │   ├── load context from vault/context/                   │  │
│  │    │   ├── claude_bridge.reason(task, context, system_prompt)  │  │
│  │    │   └── write plan to task file                             │  │
│  │    │                                                           │  │
│  │    ├── APPROVAL PHASE                                          │  │
│  │    │   ├── set status: awaiting-approval                      │  │
│  │    │   ├── update dashboard.md                                 │  │
│  │    │   └── approval_gate.wait_for_approval(task)              │  │
│  │    │       └── polls task file for status change               │  │
│  │    │                                                           │  │
│  │    ├── EXECUTE PHASE                                           │  │
│  │    │   ├── action_dispatcher.dispatch(plan_steps)              │  │
│  │    │   │   └── calls MCP server tools                         │  │
│  │    │   └── capture results                                     │  │
│  │    │                                                           │  │
│  │    ├── LOG PHASE                                               │  │
│  │    │   ├── logger.log_action(task, action, result)            │  │
│  │    │   ├── update task status (completed/failed)              │  │
│  │    │   ├── move to archive if done                             │  │
│  │    │   └── update dashboard.md                                 │  │
│  │    │                                                           │  │
│  │    └── sleep(poll_interval)                                    │  │
│  │                                                                │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  claude_bridge.py                                                    │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  def reason(task, context, prompt_template) -> Plan:           │  │
│  │      prompt = render(prompt_template, task, context)           │  │
│  │      result = subprocess.run(["claude", "-p", prompt])        │  │
│  │      return parse_plan(result.stdout)                          │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  approval_gate.py                                                    │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  def wait_for_approval(task_path, timeout) -> bool:           │  │
│  │      while not timed_out:                                      │  │
│  │          frontmatter = parse(task_path)                        │  │
│  │          if frontmatter.status == "approved": return True     │  │
│  │          if frontmatter.status == "rejected": return False    │  │
│  │          if HALT.md exists: raise HaltException               │  │
│  │          sleep(poll_interval)                                  │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
                                │
                          MCP tool call
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         MCP SERVERS                                  │
│                                                                      │
│  demo-server/ (Node.js)                                              │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  MCP Protocol Handler                                          │  │
│  │       │                                                        │  │
│  │       ├── tool: draft_email                                    │  │
│  │       │   Input:  { to, subject, body }                       │  │
│  │       │   Output: { success, message_id, preview }            │  │
│  │       │                                                        │  │
│  │       └── tool: create_file                                    │  │
│  │           Input:  { path, content, overwrite }                │  │
│  │           Output: { success, path, size_bytes }               │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Flow Diagram

### 3.1 Primary Flow (Happy Path)

```
  USER                    WATCHER              ORCHESTRATOR            MCP SERVER
   │                        │                       │                       │
   │  1. Drop task.md       │                       │                       │
   │  into vault/inbox/     │                       │                       │
   │ ─────────────────────▶ │                       │                       │
   │                        │                       │                       │
   │                        │  2. Validate &        │                       │
   │                        │     move to tasks/    │                       │
   │                        │ ─────────────────────▶│                       │
   │                        │     (.trigger file)   │                       │
   │                        │                       │                       │
   │                        │                       │  3. Load task +       │
   │                        │                       │     context           │
   │                        │                       │                       │
   │                        │                       │  4. Call Claude       │
   │                        │                       │     for plan          │
   │                        │                       │                       │
   │                        │                       │  5. Write plan        │
   │                        │                       │     to task file      │
   │                        │                       │                       │
   │  6. Review plan in     │                       │                       │
   │     Obsidian           │                       │                       │
   │◀────────────────────── │ ◀──────────────────── │                       │
   │                        │   (dashboard update)  │                       │
   │                        │                       │                       │
   │  7. Set status:        │                       │                       │
   │     approved           │                       │                       │
   │ ──────────────────────────────────────────────▶│                       │
   │                        │                       │                       │
   │                        │                       │  8. Dispatch to       │
   │                        │                       │     MCP server        │
   │                        │                       │ ─────────────────────▶│
   │                        │                       │                       │
   │                        │                       │  9. Receive result    │
   │                        │                       │ ◀─────────────────────│
   │                        │                       │                       │
   │                        │                       │  10. Log action       │
   │                        │                       │      Update status    │
   │                        │                       │      Archive task     │
   │                        │                       │                       │
   │  11. See result in     │                       │                       │
   │      Obsidian          │                       │                       │
   │◀────────────────────── │ ◀──────────────────── │                       │
   │                        │   (dashboard update)  │                       │
```

### 3.2 Error Flow

```
  ORCHESTRATOR                MCP SERVER              VAULT
       │                          │                     │
       │  1. Dispatch action      │                     │
       │ ────────────────────────▶│                     │
       │                          │                     │
       │  2. Error response       │                     │
       │ ◀────────────────────────│                     │
       │                          │                     │
       │  3. Retry once (30s)     │                     │
       │ ────────────────────────▶│                     │
       │                          │                     │
       │  4. Still failing        │                     │
       │ ◀────────────────────────│                     │
       │                          │                     │
       │  5. Log failure                                │
       │ ──────────────────────────────────────────────▶│  vault/logs/
       │                                                │
       │  6. Set task failed                            │
       │ ──────────────────────────────────────────────▶│  vault/tasks/
       │                                                │
       │  7. Update dashboard                           │
       │ ──────────────────────────────────────────────▶│  dashboard.md
       │                                                │
       │  8. STOP — wait for human                      │
       │                                                │
```

### 3.3 Kill Switch Flow

```
  USER                    ORCHESTRATOR
   │                          │
   │  Create HALT.md          │
   │ ────────────────────────▶│
   │                          │
   │                          │  Detects HALT.md
   │                          │  at start of every loop
   │                          │
   │                          │  ┌──────────────────┐
   │                          │  │ HALTED            │
   │                          │  │ All actions stop  │
   │                          │  │ Polls for removal │
   │                          │  └──────────────────┘
   │                          │
   │  Delete HALT.md          │
   │ ────────────────────────▶│
   │                          │
   │                          │  Resumes normal loop
   │                          │
```

---

## 4. File-Level Dependency Map

```
                         ┌────────────┐
                         │  run.py    │  (entry point)
                         └─────┬──────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
      ┌──────────────┐ ┌─────────────┐ ┌──────────────┐
      │ task_manager  │ │claude_bridge│ │   logger     │
      └──────┬───────┘ └──────┬──────┘ └──────┬───────┘
              │                │                │
              ▼                │                ▼
      ┌──────────────┐        │         ┌──────────────┐
      │approval_gate │        │         │ vault/logs/  │
      └──────┬───────┘        │         └──────────────┘
              │                │
              ▼                ▼
      ┌──────────────┐ ┌─────────────┐
      │ vault/tasks/ │ │  prompts/   │
      └──────────────┘ └─────────────┘
              │
              ▼
      ┌──────────────┐
      │action_dispatch│──────▶ MCP Servers
      └──────────────┘

      ┌──────────────┐
      │file_watcher  │──────▶ vault/inbox/ ──▶ vault/tasks/
      └──────┬───────┘
              │
              ▼
      ┌──────────────┐
      │markdown_parser│
      └──────────────┘
```

---

## 5. Technology Stack

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| Perception | Python + watchdog | 3.11+ | Filesystem monitoring |
| Orchestration | Python + Claude CLI | 3.11+ | Task loop, reasoning |
| Memory | Obsidian (markdown) | 1.5+ | Human interface, dashboard |
| Action | Node.js + MCP SDK | 20 LTS | Tool execution servers |
| Config | YAML + .env | — | Settings and secrets |
| Version Control | Git | — | Code versioning |

### Python Dependencies

```
watchdog>=4.0.0        # Filesystem watcher
pyyaml>=6.0            # YAML frontmatter parsing
python-dotenv>=1.0.0   # Environment variable loading
```

### Node Dependencies

```
@modelcontextprotocol/sdk   # MCP server framework
```

---

## 6. Security Boundaries

```
┌─────────────────────────────────────────────────────┐
│                   TRUST BOUNDARY                     │
│                                                      │
│   ┌───────────┐    ┌────────────┐                   │
│   │  Watchers  │    │Orchestrator│                   │
│   │ (read-only │    │ (read/write│                   │
│   │  vault)    │    │  vault)    │                   │
│   └───────────┘    └──────┬─────┘                   │
│                           │                          │
│                    ┌──────┴──────┐                   │
│                    │ APPROVAL    │ ◀── Human         │
│                    │ GATE        │                    │
│                    └──────┬──────┘                   │
│                           │ approved only            │
├───────────────────────────┼──────────────────────────┤
│                           ▼          EXTERNAL        │
│                    ┌─────────────┐                   │
│                    │ MCP Servers │ ──▶ Internet      │
│                    └─────────────┘                   │
│                                                      │
└─────────────────────────────────────────────────────┘

Secrets: .env (never in vault, never in git)
```

---

## 7. Bronze Limitations (Intentional Constraints)

| Constraint | Reason |
|---|---|
| Single-task processing | Simplicity — no concurrent task conflicts |
| Poll-based (not event-driven) | Easier to debug, predictable timing |
| CLI subprocess for Claude | No API key management needed for Claude Code |
| All actions require approval | Maximum safety for MVP demo |
| Flat file structure | No Obsidian plugins or graph logic needed |
| Single MCP server | Prove the pattern, scale later |

These constraints are **features, not bugs** — they keep the Bronze tier demo-ready and debuggable. Silver removes them incrementally.

---

*Architecture is the art of drawing lines. These lines keep perception, reasoning, memory, and action cleanly separated — making the system understandable, debuggable, and safe.*
