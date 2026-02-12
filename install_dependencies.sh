#!/usr/bin/env bash
# ============================================================================
# install_dependencies.sh — One-command setup for the AI Employee system
#
# Installs all Python and Node.js dependencies, creates the .env file,
# verifies the installation, and runs tests.
#
# Usage:
#   bash install_dependencies.sh
#
# Cross-platform: Works on Linux, macOS, and Windows (Git Bash / WSL)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       PERSONAL AI EMPLOYEE — DEPENDENCY INSTALLER           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ---------------------------------------------------------------------------
# 1. Check prerequisites
# ---------------------------------------------------------------------------
echo "[1/6] Checking prerequisites..."

# Python — handle Windows Store alias issue
if python3 --version &>/dev/null 2>&1; then
    PYTHON=python3
elif python --version &>/dev/null 2>&1; then
    PYTHON=python
elif py --version &>/dev/null 2>&1; then
    PYTHON=py
else
    echo "  ERROR: Python not found. Install Python 3.11+ and try again."
    exit 1
fi

PY_VERSION=$($PYTHON --version 2>&1)
echo "  Python: $PY_VERSION"

# Node.js
if command -v node &>/dev/null; then
    NODE_VERSION=$(node --version)
    echo "  Node.js: $NODE_VERSION"
    HAS_NODE=true
else
    echo "  Node.js: NOT FOUND (MCP server will be unavailable)"
    echo "  Install Node.js 20+ for full functionality"
    HAS_NODE=false
fi

# pip
if ! $PYTHON -m pip --version &>/dev/null; then
    echo "  ERROR: pip not found. Install pip and try again."
    exit 1
fi
echo "  pip: OK"
echo ""

# ---------------------------------------------------------------------------
# 2. Install Python dependencies
# ---------------------------------------------------------------------------
echo "[2/6] Installing Python dependencies..."
$PYTHON -m pip install -r requirements.txt --quiet
echo "  Installed: watchdog, pyyaml, python-dotenv, pytest"
echo ""

# ---------------------------------------------------------------------------
# 3. Install Node.js dependencies (if Node available)
# ---------------------------------------------------------------------------
echo "[3/6] Installing Node.js dependencies..."
if [ "$HAS_NODE" = true ]; then
    if [ -d "mcp-servers/demo-server" ]; then
        cd mcp-servers/demo-server
        npm install --silent 2>/dev/null || npm install
        cd "$SCRIPT_DIR"
        echo "  Installed: @modelcontextprotocol/sdk"
    fi
else
    echo "  Skipped (Node.js not available)"
fi
echo ""

# ---------------------------------------------------------------------------
# 4. Create .env file
# ---------------------------------------------------------------------------
echo "[4/6] Setting up environment..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  Created .env from .env.example"
    echo "  >> Edit .env to add your ANTHROPIC_API_KEY (optional for demo)"
else
    echo "  .env already exists — keeping existing configuration"
fi
echo ""

# ---------------------------------------------------------------------------
# 5. Create vault directories
# ---------------------------------------------------------------------------
echo "[5/6] Ensuring vault directories exist..."
DIRS=(
    "vault/inbox"
    "vault/needs_action"
    "vault/approved"
    "vault/completed"
    "vault/tasks/archive"
    "vault/logs"
    "vault/context"
    "vault/drafts"
)
for dir in "${DIRS[@]}"; do
    mkdir -p "$dir"
    echo "  + $dir/"
done
echo ""

# ---------------------------------------------------------------------------
# 6. Verify installation
# ---------------------------------------------------------------------------
echo "[6/6] Verifying installation..."

# Test Python imports
$PYTHON -c "
import watchdog; import yaml; import dotenv; import pytest
from pathlib import Path
print('  Python imports: OK')
" || { echo "  ERROR: Python import check failed"; exit 1; }

# Test module loading
$PYTHON -c "
from orchestrator.config import config
from orchestrator.logger import audit
from orchestrator.task_manager import TaskManager
from orchestrator.approval_gate import ApprovalGate
from orchestrator.claude_bridge import generate_plan
from orchestrator.action_dispatcher import ActionDispatcher
from orchestrator.dashboard import DashboardUpdater
print('  Orchestrator modules: OK')
" || { echo "  ERROR: Module import check failed"; exit 1; }

# Run tests
echo ""
echo "  Running tests..."
$PYTHON -m pytest tests/ -q --tb=short 2>&1 | tail -5
echo ""

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              INSTALLATION COMPLETE                          ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                             ║"
echo "║  Next step:  bash run_system.sh                             ║"
echo "║                                                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
