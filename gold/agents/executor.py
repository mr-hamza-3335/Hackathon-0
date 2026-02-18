"""Executor agent — executes approved plan steps.

The Executor takes a plan from the Planner, parses steps,
and executes them through the tool layer with permission checks.
"""

import logging
import re
import time
from typing import Any

from gold.agents.base import BaseAgent, AgentContext
from gold.tools.base import tool_executor, ToolResult

logger = logging.getLogger("gold.agents.executor")


class ExecutorAgent(BaseAgent):
    """Executes plan steps through the tool layer."""

    @property
    def name(self) -> str:
        return "executor"

    @property
    def role(self) -> str:
        return "Executes approved plan steps using available tools"

    def process(self, context: AgentContext) -> AgentContext:
        """Execute the plan steps."""
        self.log_reasoning(context, "Parsing plan steps...")

        steps = self._parse_plan(context.plan)
        self.log_reasoning(context, f"Found {len(steps)} steps to execute")

        results = []
        for i, step in enumerate(steps, 1):
            self.log_reasoning(context, f"Executing step {i}: {step['description']}")

            result = self._execute_step(step)
            results.append({
                "step": i,
                "description": step["description"],
                "tool": step["tool"],
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "duration_ms": result.duration_ms,
            })

            status = "success" if result.success else "failed"
            self.log_reasoning(context, f"Step {i} {status}: {result.output or result.error}")

            # Stop on failure
            if not result.success and result.error != "Action queued for approval":
                self.log_reasoning(context, f"Stopping execution due to failure at step {i}")
                break

        context.execution_results = results
        context.add_message(self.name, "output", f"Executed {len(results)} steps")
        return context

    def _parse_plan(self, plan: str) -> list[dict[str, str]]:
        """Parse plan text into structured steps."""
        steps = []
        for line in plan.split("\n"):
            line = line.strip()
            if not line.startswith("- [ ] Step"):
                continue

            description = line.replace("- [ ] ", "")
            tool = "none"
            approval = "no"

            if "(tool:" in line:
                meta = line[line.index("(tool:"):].strip("()")
                parts = [p.strip() for p in meta.split(",")]
                for part in parts:
                    if part.startswith("tool:"):
                        tool = part.split(":", 1)[1].strip()
                    elif part.startswith("approval:"):
                        approval = part.split(":", 1)[1].strip()

            steps.append({
                "description": description,
                "tool": tool,
                "approval": approval,
            })

        return steps

    def _execute_step(self, step: dict[str, str]) -> ToolResult:
        """Execute a single plan step."""
        tool_name = step["tool"]

        if tool_name == "none":
            return ToolResult(
                tool="none", action="noop", success=True,
                output="Completed (no tool required)",
            )

        # Map legacy tool names to new tool/action pairs
        tool_map = {
            "draft_email": ("email", "draft_email"),
            "send_email": ("email", "send_email"),
            "create_file": ("filesystem", "create_file"),
            "search_files": ("filesystem", "search_files"),
            "schedule_event": ("calendar", "schedule_event"),
            "shell_command": ("shell", "shell_command"),
        }

        mapped = tool_map.get(tool_name)
        if mapped:
            actual_tool, action = mapped
        else:
            actual_tool = tool_name
            action = tool_name

        # Build default params based on action
        params = self._build_default_params(action, step["description"])

        return tool_executor.execute(actual_tool, action, params)

    def _build_default_params(self, action: str, description: str) -> dict[str, Any]:
        """Build default parameters for common actions."""
        if action in ("draft_email", "send_email"):
            return {
                "to": "team@example.com",
                "subject": "AI Employee — Task Report",
                "body": f"Auto-generated for: {description}",
            }
        elif action == "create_file":
            return {
                "path": "vault/output/report.md",
                "content": f"# Generated Report\n\n{description}\n",
            }
        elif action == "schedule_event":
            return {
                "title": description,
                "date": "2026-02-20",
                "time": "10:00",
            }
        return {}
