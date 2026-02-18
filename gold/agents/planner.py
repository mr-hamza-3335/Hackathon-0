"""Planner agent — generates task execution plans.

The Planner analyzes the task request, considers available tools,
and produces a structured plan with steps and risk assessments.
"""

import logging
from typing import Any

from gold.agents.base import BaseAgent, AgentContext
from gold.tools.base import tool_registry

logger = logging.getLogger("gold.agents.planner")


class PlannerAgent(BaseAgent):
    """Generates execution plans for tasks."""

    @property
    def name(self) -> str:
        return "planner"

    @property
    def role(self) -> str:
        return "Analyzes tasks and generates structured execution plans"

    def __init__(self, ai_callable: Any = None) -> None:
        """Initialize with optional AI callable for real planning.

        Args:
            ai_callable: function(prompt) -> str for AI-powered planning.
                        If None, uses template-based planning.
        """
        self._ai = ai_callable

    def process(self, context: AgentContext) -> AgentContext:
        """Generate a plan for the task."""
        self.log_reasoning(context, f"Analyzing task: {context.task_title}")

        # Gather available tools
        available_tools = tool_registry.list_tools()
        tool_names = [t["name"] for t in available_tools]
        self.log_reasoning(context, f"Available tools: {', '.join(tool_names) or 'none'}")

        # Generate plan
        if self._ai:
            plan = self._generate_ai_plan(context, available_tools)
        else:
            plan = self._generate_template_plan(context, available_tools)

        context.plan = plan
        context.add_message(self.name, "output", plan)
        self.log_reasoning(context, f"Plan generated: {len(plan)} chars")

        return context

    def _generate_ai_plan(self, context: AgentContext, tools: list[dict]) -> str:
        """Use AI to generate a plan."""
        tools_desc = "\n".join(
            f"- {t['name']}: {t['description']}" for t in tools
        )
        prompt = (
            f"Task: {context.task_title}\n\n"
            f"Description:\n{context.task_body}\n\n"
            f"Available tools:\n{tools_desc}\n\n"
            "Generate a step-by-step execution plan. Use the format:\n"
            "- [ ] Step N: Description (tool: tool_name, approval: yes/no)\n"
        )
        return self._ai(prompt)

    def _generate_template_plan(self, context: AgentContext, tools: list[dict]) -> str:
        """Generate a template-based plan (no AI needed)."""
        body_lower = context.task_body.lower()

        steps = ["- [ ] Step 1: Analyze task request (tool: none, approval: no)"]

        # Detect what tools are needed
        if any(kw in body_lower for kw in ["email", "send", "draft", "message"]):
            steps.append("- [ ] Step 2: Draft email content (tool: draft_email, approval: yes)")
            steps.append("- [ ] Step 3: Send email (tool: send_email, approval: yes)")

        if any(kw in body_lower for kw in ["file", "create", "write", "report"]):
            steps.append(f"- [ ] Step {len(steps)+1}: Create output file (tool: create_file, approval: yes)")

        if any(kw in body_lower for kw in ["schedule", "calendar", "meeting", "event"]):
            steps.append(f"- [ ] Step {len(steps)+1}: Schedule event (tool: schedule_event, approval: yes)")

        if any(kw in body_lower for kw in ["search", "find", "look up"]):
            steps.append(f"- [ ] Step {len(steps)+1}: Search for information (tool: search_files, approval: no)")

        if len(steps) == 1:
            # Generic plan
            steps.append("- [ ] Step 2: Process request (tool: none, approval: no)")
            steps.append("- [ ] Step 3: Generate output (tool: create_file, approval: yes)")

        steps.append(f"- [ ] Step {len(steps)+1}: Verify results (tool: none, approval: no)")

        plan = "## Proposed Plan\n\n" + "\n".join(steps)
        return plan
