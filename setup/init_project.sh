#!/usr/bin/env bash
# ============================================================================
# init_project.sh — Personal AI Employee: Bronze Tier Project Scaffolding
#
# Usage:
#   chmod +x setup/init_project.sh
#   ./setup/init_project.sh
#
# This script creates the full directory structure and template files
# defined in SPECIFICATION.md. Safe to run multiple times (idempotent).
# ============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "=== Personal AI Employee — Project Scaffolding ==="
echo "Project root: $PROJECT_ROOT"
echo ""

# ----------------------------------------------------------------------------
# 1. Create directory structure
# ----------------------------------------------------------------------------
echo "[1/6] Creating directories..."

directories=(
    "docs"
    "setup"
    "vault/.obsidian"
    "vault/inbox"
    "vault/tasks/archive"
    "vault/logs"
    "vault/context"
    "watchers/utils"
    "orchestrator/prompts"
    "mcp-servers/demo-server/tools"
    "tests"
)

for dir in "${directories[@]}"; do
    mkdir -p "$PROJECT_ROOT/$dir"
    echo "  + $dir/"
done

echo ""

# ----------------------------------------------------------------------------
# 2. Create vault template files
# ----------------------------------------------------------------------------
echo "[2/6] Creating vault templates..."

# Dashboard
if [ ! -f "$PROJECT_ROOT/vault/dashboard.md" ]; then
cat > "$PROJECT_ROOT/vault/dashboard.md" << 'DASHBOARD'
---
title: AI Employee Dashboard
updated: ""
---

# AI Employee Dashboard

## System Status

| Component | Status |
|---|---|
| File Watcher | Stopped |
| Orchestrator | Stopped |
| MCP Servers | Stopped |

## Pending Approvals

_No pending approvals._

## Recent Actions

| Time | Task | Action | Status |
|---|---|---|---|
| — | — | — | — |

## Active Tasks

_No active tasks._

---

> **Kill Switch**: Create `HALT.md` in this vault to immediately stop all automation.
DASHBOARD
echo "  + vault/dashboard.md"
fi

# Inbox template
if [ ! -f "$PROJECT_ROOT/vault/inbox/_template.md" ]; then
cat > "$PROJECT_ROOT/vault/inbox/_template.md" << 'TEMPLATE'
---
id: task-YYYYMMDD-NNN
status: new
priority: medium
source: manual
tags: []
approval_required: true
---

## Request

Describe what you want the AI Employee to do.

## Context

Any additional context, links, or references.
TEMPLATE
echo "  + vault/inbox/_template.md"
fi

# User profile
if [ ! -f "$PROJECT_ROOT/vault/context/user-profile.md" ]; then
cat > "$PROJECT_ROOT/vault/context/user-profile.md" << 'PROFILE'
---
title: User Profile
---

# User Profile

## Identity

- **Name**: [Your Name]
- **Email**: [your@email.com]
- **Role**: [Your Role]

## Preferences

- Communication style: Professional but friendly
- Preferred email sign-off: Best regards
- Time zone: UTC

## Notes

Add any preferences the AI Employee should know about.
PROFILE
echo "  + vault/context/user-profile.md"
fi

# Tools registry
if [ ! -f "$PROJECT_ROOT/vault/context/tools-registry.md" ]; then
cat > "$PROJECT_ROOT/vault/context/tools-registry.md" << 'TOOLS'
---
title: Tools Registry
---

# Available MCP Tools

## demo-server

### draft_email

- **Description**: Drafts an email and saves it for review
- **Input**: `{ to, subject, body }`
- **Output**: `{ success, message_id, preview }`
- **Risk Tier**: T3 (External Write)
- **Approval**: Required

### create_file

- **Description**: Creates a file on the local filesystem
- **Input**: `{ path, content, overwrite }`
- **Output**: `{ success, path, size_bytes }`
- **Risk Tier**: T1 (Internal Write)
- **Approval**: Not required (Bronze: required)
TOOLS
echo "  + vault/context/tools-registry.md"
fi

# Log template
if [ ! -f "$PROJECT_ROOT/vault/logs/_log-template.md" ]; then
cat > "$PROJECT_ROOT/vault/logs/_log-template.md" << 'LOG'
---
timestamp: ""
task_id: ""
action: ""
tool: ""
status: ""
duration_ms: 0
---

## Action Log

**Input**:
**Output**:
**Approval**:
LOG
echo "  + vault/logs/_log-template.md"
fi

# HALT.md (disabled by default)
if [ ! -f "$PROJECT_ROOT/vault/HALT.md.disabled" ]; then
cat > "$PROJECT_ROOT/vault/HALT.md.disabled" << 'HALT'
# SYSTEM HALTED

Rename this file to `HALT.md` to stop all AI Employee automation.

Delete or rename away from `HALT.md` to resume.
HALT
echo "  + vault/HALT.md.disabled"
fi

echo ""

# ----------------------------------------------------------------------------
# 3. Create Python files
# ----------------------------------------------------------------------------
echo "[3/6] Creating Python source files..."

# watchers/__init__.py
touch "$PROJECT_ROOT/watchers/__init__.py"
touch "$PROJECT_ROOT/watchers/utils/__init__.py"
touch "$PROJECT_ROOT/orchestrator/__init__.py"

# watchers/config.py
if [ ! -f "$PROJECT_ROOT/watchers/config.py" ]; then
cat > "$PROJECT_ROOT/watchers/config.py" << 'PYCONFIG'
"""Watcher configuration loader."""

from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

VAULT_ROOT = Path(os.getenv("VAULT_ROOT", "./vault"))
INBOX_PATH = VAULT_ROOT / "inbox"
TASKS_PATH = VAULT_ROOT / "tasks"
POLL_INTERVAL = int(os.getenv("WATCHER_POLL_INTERVAL", "3"))
PYCONFIG
echo "  + watchers/config.py"
fi

# watchers/utils/markdown_parser.py
if [ ! -f "$PROJECT_ROOT/watchers/utils/markdown_parser.py" ]; then
cat > "$PROJECT_ROOT/watchers/utils/markdown_parser.py" << 'PARSER'
"""Parse YAML frontmatter from markdown task files."""

from pathlib import Path
from typing import Any
import yaml


REQUIRED_FIELDS = {"id", "status"}


def parse_frontmatter(file_path: Path) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and body from a markdown file.

    Returns:
        Tuple of (frontmatter_dict, body_string).
        Returns empty dict if no frontmatter found.
    """
    text = file_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return frontmatter, body


def validate_frontmatter(frontmatter: dict[str, Any]) -> list[str]:
    """Validate that required fields are present.

    Returns:
        List of missing field names. Empty list means valid.
    """
    missing = REQUIRED_FIELDS - set(frontmatter.keys())
    return sorted(missing)


def update_frontmatter(file_path: Path, updates: dict[str, Any]) -> None:
    """Update specific fields in a file's YAML frontmatter."""
    frontmatter, body = parse_frontmatter(file_path)
    frontmatter.update(updates)
    yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    new_content = f"---\n{yaml_str}---\n\n{body}\n"
    file_path.write_text(new_content, encoding="utf-8")
PARSER
echo "  + watchers/utils/markdown_parser.py"
fi

# watchers/file_watcher.py (stub)
if [ ! -f "$PROJECT_ROOT/watchers/file_watcher.py" ]; then
cat > "$PROJECT_ROOT/watchers/file_watcher.py" << 'WATCHER'
"""File watcher — monitors vault/inbox/ for new task files."""

import logging
import shutil
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from watchers.config import INBOX_PATH, TASKS_PATH, POLL_INTERVAL
from watchers.utils.markdown_parser import parse_frontmatter, validate_frontmatter, update_frontmatter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [WATCHER] %(message)s")
logger = logging.getLogger(__name__)


class InboxHandler(FileSystemEventHandler):
    """Handle new files appearing in vault/inbox/."""

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        if file_path.suffix != ".md" or file_path.name.startswith("_"):
            return

        logger.info(f"New file detected: {file_path.name}")
        self._process_task(file_path)

    def _process_task(self, file_path: Path) -> None:
        """Validate and move a task file from inbox to tasks."""
        try:
            frontmatter, body = parse_frontmatter(file_path)

            missing = validate_frontmatter(frontmatter)
            if missing:
                logger.warning(f"Invalid task {file_path.name}: missing fields {missing}")
                return

            # Set status to pending
            update_frontmatter(file_path, {"status": "pending"})

            # Move to tasks directory
            dest = TASKS_PATH / file_path.name
            shutil.move(str(file_path), str(dest))
            logger.info(f"Task moved to: {dest.name}")

            # Write trigger file for orchestrator
            trigger = TASKS_PATH / ".trigger"
            trigger.write_text(frontmatter.get("id", file_path.stem), encoding="utf-8")
            logger.info(f"Trigger written for task: {frontmatter.get('id', 'unknown')}")

        except Exception:
            logger.exception(f"Error processing {file_path.name}")


def start_watcher() -> None:
    """Start watching the inbox directory."""
    INBOX_PATH.mkdir(parents=True, exist_ok=True)
    TASKS_PATH.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    observer.schedule(InboxHandler(), str(INBOX_PATH), recursive=False)
    observer.start()
    logger.info(f"Watching: {INBOX_PATH.resolve()}")

    try:
        while True:
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Shutting down watcher...")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    start_watcher()
WATCHER
echo "  + watchers/file_watcher.py"
fi

# orchestrator stubs
for file in run.py claude_bridge.py task_manager.py approval_gate.py action_dispatcher.py logger.py config.py; do
    target="$PROJECT_ROOT/orchestrator/$file"
    if [ ! -f "$target" ]; then
        echo "\"\"\"$(echo $file | sed 's/.py//' | sed 's/_/ /g') — stub for Bronze MVP.\"\"\"" > "$target"
        echo "  + orchestrator/$file (stub)"
    fi
done

echo ""

# ----------------------------------------------------------------------------
# 4. Create orchestrator prompt templates
# ----------------------------------------------------------------------------
echo "[4/6] Creating prompt templates..."

if [ ! -f "$PROJECT_ROOT/orchestrator/prompts/system.md" ]; then
cat > "$PROJECT_ROOT/orchestrator/prompts/system.md" << 'SYSPROMPT'
# System Prompt — AI Employee

You are a Personal AI Employee operating in Bronze mode.

## Your Role
- You help the user by planning and executing tasks
- You always propose a plan before taking action
- You never act without explicit human approval

## Rules
1. Read the task description carefully
2. Check available tools in the tools registry
3. Generate a clear, step-by-step plan
4. Each step that calls an external tool must be marked as requiring approval
5. Never fabricate data — if you need information, say so
6. Keep plans concise and actionable

## Output Format
Return your plan as a markdown checklist:
```
## Proposed Plan
- [ ] Step 1: Description (tool: tool_name, approval: yes/no)
- [ ] Step 2: Description (tool: tool_name, approval: yes/no)
```

If the task requires generating content (email, document), include it under:
```
## Draft Output
[Your generated content here]
```
SYSPROMPT
echo "  + orchestrator/prompts/system.md"
fi

if [ ! -f "$PROJECT_ROOT/orchestrator/prompts/plan_task.md" ]; then
cat > "$PROJECT_ROOT/orchestrator/prompts/plan_task.md" << 'PLANTASK'
# Plan Task

## Task Details
{task_content}

## User Context
{user_context}

## Available Tools
{tools_registry}

## Instructions
Generate a plan to complete this task. Follow the system prompt format.
PLANTASK
echo "  + orchestrator/prompts/plan_task.md"
fi

if [ ! -f "$PROJECT_ROOT/orchestrator/prompts/review_result.md" ]; then
cat > "$PROJECT_ROOT/orchestrator/prompts/review_result.md" << 'REVIEW'
# Review Action Result

## Original Task
{task_content}

## Executed Action
{action_description}

## Result
{action_result}

## Instructions
Verify whether the action completed successfully. Respond with:
- VERIFIED: if the result matches the expected outcome
- FAILED: if something went wrong, with explanation
REVIEW
echo "  + orchestrator/prompts/review_result.md"
fi

echo ""

# ----------------------------------------------------------------------------
# 5. Create config and environment files
# ----------------------------------------------------------------------------
echo "[5/6] Creating config files..."

# .env.example
if [ ! -f "$PROJECT_ROOT/.env.example" ]; then
cat > "$PROJECT_ROOT/.env.example" << 'ENVFILE'
# Claude API
ANTHROPIC_API_KEY=sk-ant-xxxxx

# MCP Server Config
MCP_DEMO_PORT=3100

# Vault Path (override default)
# VAULT_ROOT=./vault

# Watcher
WATCHER_POLL_INTERVAL=3

# Logging
LOG_LEVEL=INFO
ENVFILE
echo "  + .env.example"
fi

# orchestrator/config.yaml
if [ ! -f "$PROJECT_ROOT/orchestrator/config.yaml" ]; then
cat > "$PROJECT_ROOT/orchestrator/config.yaml" << 'CONFIG'
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
CONFIG
echo "  + orchestrator/config.yaml"
fi

# .gitignore
if [ ! -f "$PROJECT_ROOT/.gitignore" ]; then
cat > "$PROJECT_ROOT/.gitignore" << 'GITIGNORE'
# Environment
.env
.env.local

# Python
__pycache__/
*.pyc
*.pyo
.venv/
venv/

# Node
node_modules/
package-lock.json

# Obsidian
vault/.obsidian/workspace.json
vault/.obsidian/workspace-mobile.json

# OS
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/

# Trigger files
.trigger
GITIGNORE
echo "  + .gitignore"
fi

# requirements.txt
if [ ! -f "$PROJECT_ROOT/requirements.txt" ]; then
cat > "$PROJECT_ROOT/requirements.txt" << 'REQS'
watchdog>=4.0.0
pyyaml>=6.0.0
python-dotenv>=1.0.0
REQS
echo "  + requirements.txt"
fi

echo ""

# ----------------------------------------------------------------------------
# 6. Create test stubs
# ----------------------------------------------------------------------------
echo "[6/6] Creating test stubs..."

for test_file in test_file_watcher.py test_task_manager.py test_approval_gate.py test_markdown_parser.py; do
    target="$PROJECT_ROOT/tests/$test_file"
    if [ ! -f "$target" ]; then
        module=$(echo "$test_file" | sed 's/^test_//' | sed 's/.py$//')
        echo "\"\"\"Tests for $module.\"\"\"" > "$target"
        echo "  + tests/$test_file (stub)"
    fi
done

echo ""
echo "=== Scaffolding Complete ==="
echo ""
echo "Next steps:"
echo "  1. cp .env.example .env && edit .env with your API keys"
echo "  2. pip install -r requirements.txt"
echo "  3. Open vault/ as an Obsidian vault"
echo "  4. python -m watchers.file_watcher  (start watcher)"
echo "  5. Drop a task into vault/inbox/ to test"
echo ""
