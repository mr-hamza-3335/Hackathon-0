"""Shell tool — sandboxed command execution.

Runs shell commands within strict safety boundaries.
All commands are validated through the sandbox before execution.
"""

import logging
import subprocess
from typing import Any

from gold.tools.base import BaseTool, ToolResult
from gold.security.permissions import RiskTier, sandbox

logger = logging.getLogger("gold.tools.shell")


class ShellTool(BaseTool):
    """Sandboxed shell command execution."""

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return "Execute shell commands within a sandboxed environment"

    @property
    def actions(self) -> dict[str, str]:
        return {
            "shell_command": "Execute a shell command (sandboxed)",
        }

    def get_risk_tier(self, action: str) -> RiskTier:
        return RiskTier.T3  # All shell commands are high risk

    def execute(self, action: str, params: dict[str, Any]) -> ToolResult:
        if action != "shell_command":
            return ToolResult(tool=self.name, action=action, success=False,
                            error=f"Unknown action: {action}", output=None)

        command = params.get("command", "")
        timeout = min(params.get("timeout", 30), sandbox.MAX_SHELL_TIMEOUT)
        cwd = params.get("cwd")

        if not command:
            return ToolResult(tool=self.name, action=action, success=False,
                            error="'command' is required", output=None)

        # Sandbox validation
        valid, reason = sandbox.validate_shell_command(command)
        if not valid:
            logger.warning(f"Shell command blocked: {command} — {reason}")
            return ToolResult(tool=self.name, action=action, success=False,
                            error=f"Command blocked: {reason}", output=None)

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )

            output = {
                "stdout": result.stdout[:5000],  # Limit output size
                "stderr": result.stderr[:2000],
                "returncode": result.returncode,
            }

            success = result.returncode == 0
            return ToolResult(
                tool=self.name, action=action,
                success=success, output=output,
                error=result.stderr[:500] if not success else "",
            )

        except subprocess.TimeoutExpired:
            return ToolResult(tool=self.name, action=action, success=False,
                            error=f"Command timed out after {timeout}s", output=None)
        except Exception as e:
            return ToolResult(tool=self.name, action=action, success=False,
                            error=str(e), output=None)
