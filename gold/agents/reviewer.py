"""Reviewer agent — validates execution results.

The Reviewer examines execution outputs, checks for errors,
and produces a verdict on whether the task was completed successfully.
"""

import logging
from typing import Any

from gold.agents.base import BaseAgent, AgentContext

logger = logging.getLogger("gold.agents.reviewer")


class ReviewerAgent(BaseAgent):
    """Reviews and validates execution results."""

    @property
    def name(self) -> str:
        return "reviewer"

    @property
    def role(self) -> str:
        return "Validates execution results and provides quality assessment"

    def __init__(self, ai_callable: Any = None) -> None:
        self._ai = ai_callable

    def process(self, context: AgentContext) -> AgentContext:
        """Review the execution results."""
        self.log_reasoning(context, "Reviewing execution results...")

        results = context.execution_results
        if not results:
            context.review_verdict = "no_results"
            context.add_message(self.name, "output", "No execution results to review")
            return context

        # Analyze results
        total = len(results)
        successes = sum(1 for r in results if r.get("success"))
        failures = total - successes

        self.log_reasoning(context, f"Results: {successes}/{total} succeeded, {failures} failed")

        # Check each result
        issues = []
        for r in results:
            if not r.get("success"):
                issues.append(f"Step {r['step']}: {r.get('error', 'unknown error')}")
            elif r.get("error") == "Action queued for approval":
                issues.append(f"Step {r['step']}: Awaiting approval")

        # Generate verdict
        if failures == 0:
            verdict = "approved"
            summary = f"All {total} steps completed successfully"
        elif failures < total:
            verdict = "partial"
            summary = f"{successes}/{total} steps succeeded. Issues: {'; '.join(issues)}"
        else:
            verdict = "rejected"
            summary = f"All steps failed. Issues: {'; '.join(issues)}"

        context.review_verdict = verdict
        context.add_message(self.name, "output", f"Verdict: {verdict} — {summary}")
        self.log_reasoning(context, f"Verdict: {verdict}")

        # If AI is available, get detailed review
        if self._ai and results:
            detailed = self._ai_review(context)
            context.add_message(self.name, "reasoning", f"AI Review: {detailed}")

        return context

    def _ai_review(self, context: AgentContext) -> str:
        """Get AI-powered review of results."""
        results_text = "\n".join(
            f"Step {r['step']}: {'OK' if r['success'] else 'FAIL'} — {r.get('output', r.get('error', ''))}"
            for r in context.execution_results
        )
        prompt = (
            f"Task: {context.task_title}\n"
            f"Plan:\n{context.plan}\n\n"
            f"Results:\n{results_text}\n\n"
            "Provide a brief quality assessment."
        )
        return self._ai(prompt)
