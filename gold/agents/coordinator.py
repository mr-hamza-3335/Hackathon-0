"""Agent Coordinator — orchestrates multi-agent pipeline.

Runs the Planner → Executor → Reviewer pipeline and logs
all agent reasoning for auditability.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gold.agents.base import AgentContext
from gold.agents.planner import PlannerAgent
from gold.agents.executor import ExecutorAgent
from gold.agents.reviewer import ReviewerAgent

logger = logging.getLogger("gold.agents.coordinator")


class AgentCoordinator:
    """Coordinates the multi-agent reasoning pipeline."""

    def __init__(self, ai_callable: Any = None, vault_root: str = "./vault") -> None:
        self.planner = PlannerAgent(ai_callable=ai_callable)
        self.executor = ExecutorAgent()
        self.reviewer = ReviewerAgent(ai_callable=ai_callable)
        self.vault_root = Path(vault_root)

    def run_pipeline(self, task_id: str, title: str, body: str) -> AgentContext:
        """Run the full Planner → Executor → Reviewer pipeline.

        Returns the final context with all reasoning logged.
        """
        context = AgentContext(
            task_id=task_id,
            task_title=title,
            task_body=body,
        )

        logger.info(f"Starting agent pipeline for task: {task_id}")

        # Phase 1: Planning
        context.add_message("coordinator", "input", f"Starting pipeline for: {title}")
        context = self.planner.process(context)

        # Phase 2: Execution
        context = self.executor.process(context)

        # Phase 3: Review
        context = self.reviewer.process(context)

        # Save reasoning log
        self._save_reasoning_log(context)

        logger.info(f"Pipeline complete: {task_id} — verdict: {context.review_verdict}")
        return context

    def run_planning_only(self, task_id: str, title: str, body: str) -> AgentContext:
        """Run only the planning phase."""
        context = AgentContext(task_id=task_id, task_title=title, task_body=body)
        context = self.planner.process(context)
        return context

    def run_execution(self, context: AgentContext) -> AgentContext:
        """Run execution on an existing context with a plan."""
        context = self.executor.process(context)
        context = self.reviewer.process(context)
        self._save_reasoning_log(context)
        return context

    def _save_reasoning_log(self, context: AgentContext) -> None:
        """Save the full reasoning log to vault/logs/."""
        logs_dir = self.vault_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        filename = f"{now.strftime('%Y-%m-%d_%H-%M-%S')}_agent-reasoning_{context.task_id}.md"
        log_path = logs_dir / filename

        content = f"""---
type: agent-reasoning
task_id: {context.task_id}
task_title: "{context.task_title}"
verdict: {context.review_verdict}
agents: [planner, executor, reviewer]
timestamp: {now.isoformat(timespec='seconds')}
---

# Agent Reasoning Log — {context.task_title}

## Messages

{context.get_reasoning_log()}

## Plan

{context.plan}

## Execution Results

"""
        for r in context.execution_results:
            status = "OK" if r.get("success") else "FAIL"
            content += f"- Step {r['step']}: [{status}] {r['description']}\n"
            if r.get("error"):
                content += f"  Error: {r['error']}\n"

        content += f"\n## Verdict: {context.review_verdict}\n"

        log_path.write_text(content, encoding="utf-8")
        logger.info(f"Reasoning log saved: {filename}")
