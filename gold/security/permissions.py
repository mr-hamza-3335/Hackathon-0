"""Permission system — Gold tier security layer.

Defines risk tiers, permission gates, and action approval queues.
All tool executions must pass through the permission filter before running.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from datetime import datetime, timezone

logger = logging.getLogger("gold.security")


class RiskTier(str, Enum):
    """Risk classification for actions."""
    T0 = "T0"  # Read-only, always auto-approved
    T1 = "T1"  # Low risk, auto-approved in Gold+
    T2 = "T2"  # Medium risk, requires approval
    T3 = "T3"  # High risk, requires approval + confirmation
    T4 = "T4"  # Critical, requires multi-step approval


@dataclass
class Permission:
    """A permission grant for a specific action type."""
    action: str
    risk_tier: RiskTier
    allowed: bool = True
    requires_approval: bool = False
    max_per_hour: int = 100
    description: str = ""


@dataclass
class ActionRequest:
    """A request to perform an action that must be permission-checked."""
    id: str
    action: str
    tool: str
    parameters: dict[str, Any]
    risk_tier: RiskTier
    requested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "pending"  # pending, approved, denied, executed
    approved_at: str | None = None
    denied_reason: str | None = None


class PermissionRegistry:
    """Central registry of permissions and risk classifications."""

    # Default risk tier assignments for known tools
    DEFAULT_RISK_TIERS: dict[str, RiskTier] = {
        # T0 — read only
        "read_file": RiskTier.T0,
        "list_files": RiskTier.T0,
        "search_files": RiskTier.T0,
        "get_calendar": RiskTier.T0,
        # T1 — low risk
        "draft_email": RiskTier.T1,
        "create_file": RiskTier.T1,
        "schedule_event": RiskTier.T1,
        # T2 — medium risk
        "send_email": RiskTier.T2,
        "modify_file": RiskTier.T2,
        "delete_file": RiskTier.T2,
        # T3 — high risk
        "shell_command": RiskTier.T3,
        "bulk_email": RiskTier.T3,
        # T4 — critical
        "admin_command": RiskTier.T4,
        "system_config": RiskTier.T4,
    }

    def __init__(self) -> None:
        self._permissions: dict[str, Permission] = {}
        self._rate_counters: dict[str, list[float]] = {}
        self._approval_queue: list[ActionRequest] = []
        self._init_defaults()

    def _init_defaults(self) -> None:
        """Initialize default permissions from risk tier map."""
        for action, tier in self.DEFAULT_RISK_TIERS.items():
            self._permissions[action] = Permission(
                action=action,
                risk_tier=tier,
                requires_approval=tier in (RiskTier.T2, RiskTier.T3, RiskTier.T4),
            )

    def get_risk_tier(self, action: str) -> RiskTier:
        """Get the risk tier for an action."""
        perm = self._permissions.get(action)
        if perm:
            return perm.risk_tier
        return RiskTier.T3  # Unknown actions default to high risk

    def register_permission(self, permission: Permission) -> None:
        """Register or update a permission."""
        self._permissions[permission.action] = permission

    def check_permission(self, action: str) -> tuple[bool, str]:
        """Check if an action is allowed.

        Returns (allowed, reason).
        """
        perm = self._permissions.get(action)
        if not perm:
            return False, f"Unknown action '{action}' — denied by default"

        if not perm.allowed:
            return False, f"Action '{action}' is explicitly disabled"

        # Rate limit check
        if not self._check_rate_limit(action, perm.max_per_hour):
            return False, f"Rate limit exceeded for '{action}' ({perm.max_per_hour}/hour)"

        return True, "allowed"

    def _check_rate_limit(self, action: str, max_per_hour: int) -> bool:
        """Check if an action is within its rate limit."""
        now = time.time()
        hour_ago = now - 3600

        if action not in self._rate_counters:
            self._rate_counters[action] = []

        # Prune old entries
        self._rate_counters[action] = [
            t for t in self._rate_counters[action] if t > hour_ago
        ]

        return len(self._rate_counters[action]) < max_per_hour

    def record_execution(self, action: str) -> None:
        """Record that an action was executed (for rate limiting)."""
        if action not in self._rate_counters:
            self._rate_counters[action] = []
        self._rate_counters[action].append(time.time())

    def requires_approval(self, action: str) -> bool:
        """Check if an action requires human approval."""
        perm = self._permissions.get(action)
        if not perm:
            return True  # Unknown actions require approval
        return perm.requires_approval

    def queue_for_approval(self, request: ActionRequest) -> None:
        """Add an action request to the approval queue."""
        request.status = "pending"
        self._approval_queue.append(request)
        logger.info(f"Action queued for approval: {request.action} ({request.id})")

    def get_pending_approvals(self) -> list[ActionRequest]:
        """Get all pending approval requests."""
        return [r for r in self._approval_queue if r.status == "pending"]

    def approve_request(self, request_id: str) -> bool:
        """Approve a pending action request."""
        for req in self._approval_queue:
            if req.id == request_id and req.status == "pending":
                req.status = "approved"
                req.approved_at = datetime.now(timezone.utc).isoformat()
                logger.info(f"Action approved: {req.action} ({req.id})")
                return True
        return False

    def deny_request(self, request_id: str, reason: str = "") -> bool:
        """Deny a pending action request."""
        for req in self._approval_queue:
            if req.id == request_id and req.status == "pending":
                req.status = "denied"
                req.denied_reason = reason
                logger.info(f"Action denied: {req.action} ({req.id}) — {reason}")
                return True
        return False


class Sandbox:
    """Sandboxed execution environment for tools.

    Restricts what tools can access and enforces boundaries.
    """

    # Directories tools are allowed to access
    ALLOWED_PATHS: list[str] = [
        "vault/",
        "output/",
    ]

    # Blocked shell commands
    BLOCKED_COMMANDS: list[str] = [
        "rm -rf /",
        "format",
        "shutdown",
        "reboot",
        "del /s",
        "mkfs",
        "dd if=",
        ":(){:|:&};:",
    ]

    # Max file size tools can create (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024

    # Max shell command timeout
    MAX_SHELL_TIMEOUT = 30

    def __init__(self, vault_root: str = "./vault") -> None:
        self.vault_root = vault_root

    def validate_path(self, path: str) -> tuple[bool, str]:
        """Check if a file path is within allowed boundaries."""
        from pathlib import Path
        resolved = str(Path(path).resolve())
        vault_resolved = str(Path(self.vault_root).resolve())

        if resolved.startswith(vault_resolved):
            return True, "path within vault"

        for allowed in self.ALLOWED_PATHS:
            if path.startswith(allowed) or resolved.startswith(str(Path(allowed).resolve())):
                return True, f"path within {allowed}"

        # Also allow paths that are under the vault root (relative paths)
        try:
            Path(path).resolve().relative_to(Path(self.vault_root).resolve())
            return True, "path within vault (relative)"
        except ValueError:
            pass

        return False, f"path '{path}' is outside allowed directories"

    def validate_shell_command(self, command: str) -> tuple[bool, str]:
        """Check if a shell command is safe to execute."""
        cmd_lower = command.lower().strip()

        for blocked in self.BLOCKED_COMMANDS:
            if blocked.lower() in cmd_lower:
                return False, f"blocked command pattern: '{blocked}'"

        # Block commands that modify system files
        if any(cmd_lower.startswith(p) for p in ["sudo ", "su ", "chmod 777"]):
            return False, "system-level commands are not allowed"

        return True, "command allowed"

    def validate_file_size(self, size_bytes: int) -> tuple[bool, str]:
        """Check if a file size is within limits."""
        if size_bytes > self.MAX_FILE_SIZE:
            return False, f"file size {size_bytes} exceeds limit {self.MAX_FILE_SIZE}"
        return True, "size within limits"


# Singleton instances
permissions = PermissionRegistry()
sandbox = Sandbox()
