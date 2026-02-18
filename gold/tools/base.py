"""Base tool interface — Gold tier tool abstraction.

All system tools and plugins must implement the BaseTool interface.
Tools are registered in the ToolRegistry and executed through the
permission-filtered ToolExecutor.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timezone

from gold.security.permissions import (
    RiskTier, permissions, sandbox, ActionRequest,
)

logger = logging.getLogger("gold.tools")


@dataclass
class ToolResult:
    """Result of a tool execution."""
    tool: str
    action: str
    success: bool
    output: Any
    error: str = ""
    duration_ms: int = 0
    risk_tier: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BaseTool(ABC):
    """Abstract base class for all tools in the Gold tier.

    Subclasses must implement:
      - name: unique tool identifier
      - description: human-readable description
      - actions: dict of action_name -> description
      - execute: the actual tool logic
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable tool description."""
        ...

    @property
    @abstractmethod
    def actions(self) -> dict[str, str]:
        """Map of action_name -> description."""
        ...

    @abstractmethod
    def execute(self, action: str, params: dict[str, Any]) -> ToolResult:
        """Execute a tool action with given parameters."""
        ...

    def get_risk_tier(self, action: str) -> RiskTier:
        """Get risk tier for a specific action. Override for custom tiers."""
        return permissions.get_risk_tier(action)


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.info(f"Tool registered: {tool.name} ({len(tool.actions)} actions)")

    def unregister(self, name: str) -> None:
        """Unregister a tool."""
        if name in self._tools:
            del self._tools[name]
            logger.info(f"Tool unregistered: {name}")

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "actions": t.actions,
            }
            for t in self._tools.values()
        ]

    def list_names(self) -> list[str]:
        """List all tool names."""
        return list(self._tools.keys())


class ToolExecutor:
    """Executes tools through the permission and sandbox layers."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def execute(self, tool_name: str, action: str, params: dict[str, Any]) -> ToolResult:
        """Execute a tool action with permission checks.

        Flow:
        1. Look up tool in registry
        2. Check permissions
        3. Validate through sandbox
        4. Execute tool
        5. Record execution
        """
        tool = self.registry.get(tool_name)
        if not tool:
            return ToolResult(
                tool=tool_name, action=action, success=False,
                error=f"Tool '{tool_name}' not found",
            )

        # Permission check
        allowed, reason = permissions.check_permission(action)
        if not allowed:
            logger.warning(f"Permission denied: {tool_name}.{action} — {reason}")
            return ToolResult(
                tool=tool_name, action=action, success=False,
                error=f"Permission denied: {reason}",
                risk_tier=str(permissions.get_risk_tier(action)),
            )

        # Check if approval is needed
        if permissions.requires_approval(action):
            request = ActionRequest(
                id=f"{tool_name}-{action}-{int(time.time())}",
                action=action,
                tool=tool_name,
                parameters=params,
                risk_tier=tool.get_risk_tier(action),
            )
            permissions.queue_for_approval(request)
            return ToolResult(
                tool=tool_name, action=action, success=False,
                output=None,
                error="Action queued for approval",
                risk_tier=str(request.risk_tier),
            )

        # Execute
        start = time.time()
        try:
            result = tool.execute(action, params)
            result.duration_ms = int((time.time() - start) * 1000)
            result.risk_tier = str(tool.get_risk_tier(action))
            permissions.record_execution(action)
            logger.info(f"Tool executed: {tool_name}.{action} ({result.duration_ms}ms)")
            return result
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            logger.error(f"Tool failed: {tool_name}.{action} — {e}")
            return ToolResult(
                tool=tool_name, action=action, success=False,
                error=str(e), duration_ms=elapsed,
                risk_tier=str(tool.get_risk_tier(action)),
            )


# Singleton registry and executor
tool_registry = ToolRegistry()
tool_executor = ToolExecutor(tool_registry)
