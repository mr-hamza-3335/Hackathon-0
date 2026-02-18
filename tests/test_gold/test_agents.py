"""Tests for Gold tier multi-agent reasoning system."""

import pytest
from pathlib import Path
from gold.agents.base import AgentContext, AgentMessage
from gold.agents.planner import PlannerAgent
from gold.agents.executor import ExecutorAgent
from gold.agents.reviewer import ReviewerAgent
from gold.agents.coordinator import AgentCoordinator
from gold.tools.base import ToolRegistry, tool_registry
from gold.tools.filesystem import FilesystemTool
from gold.tools.email import EmailTool
from gold.tools.calendar import CalendarTool


@pytest.fixture
def tmp_vault(tmp_path):
    (tmp_path / "tasks").mkdir()
    (tmp_path / "drafts").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "output").mkdir()
    return tmp_path


@pytest.fixture
def setup_tools(tmp_vault):
    """Register tools for testing."""
    tool_registry._tools.clear()
    tool_registry.register(FilesystemTool(vault_root=str(tmp_vault)))
    tool_registry.register(EmailTool(vault_root=str(tmp_vault)))
    tool_registry.register(CalendarTool(vault_root=str(tmp_vault)))
    yield
    tool_registry._tools.clear()


class TestAgentContext:
    def test_add_message(self):
        ctx = AgentContext(task_id="t1", task_title="Test", task_body="body")
        ctx.add_message("planner", "reasoning", "Analyzing task")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].agent == "planner"

    def test_reasoning_log(self):
        ctx = AgentContext(task_id="t1", task_title="Test", task_body="body")
        ctx.add_message("planner", "reasoning", "Step 1")
        ctx.add_message("executor", "reasoning", "Step 2")
        log = ctx.get_reasoning_log()
        assert "planner" in log
        assert "executor" in log


class TestPlannerAgent:
    def test_template_plan_email(self, setup_tools):
        planner = PlannerAgent()
        ctx = AgentContext(
            task_id="t1",
            task_title="Send weekly email",
            task_body="Send a weekly update email to the team",
        )
        ctx = planner.process(ctx)
        assert ctx.plan
        assert "draft_email" in ctx.plan
        assert len(ctx.messages) > 0

    def test_template_plan_file(self, setup_tools):
        planner = PlannerAgent()
        ctx = AgentContext(
            task_id="t2",
            task_title="Create report",
            task_body="Create a status report file",
        )
        ctx = planner.process(ctx)
        assert "create_file" in ctx.plan

    def test_template_plan_generic(self, setup_tools):
        planner = PlannerAgent()
        ctx = AgentContext(
            task_id="t3",
            task_title="Do something",
            task_body="Vague request with no keywords",
        )
        ctx = planner.process(ctx)
        assert "Step 1" in ctx.plan

    def test_ai_plan_with_callable(self, setup_tools):
        def mock_ai(prompt):
            return "## Proposed Plan\n\n- [ ] Step 1: Mock plan (tool: none, approval: no)"

        planner = PlannerAgent(ai_callable=mock_ai)
        ctx = AgentContext(task_id="t4", task_title="Test", task_body="body")
        ctx = planner.process(ctx)
        assert "Mock plan" in ctx.plan


class TestExecutorAgent:
    def test_execute_noop_steps(self, setup_tools):
        executor = ExecutorAgent()
        ctx = AgentContext(task_id="t1", task_title="Test", task_body="body")
        ctx.plan = "- [ ] Step 1: Analyze (tool: none, approval: no)\n- [ ] Step 2: Review (tool: none, approval: no)"
        ctx = executor.process(ctx)
        assert len(ctx.execution_results) == 2
        assert all(r["success"] for r in ctx.execution_results)

    def test_execute_with_tools(self, setup_tools):
        executor = ExecutorAgent()
        ctx = AgentContext(task_id="t2", task_title="Test", task_body="body")
        ctx.plan = "- [ ] Step 1: Draft email (tool: draft_email, approval: no)"
        ctx = executor.process(ctx)
        assert len(ctx.execution_results) == 1


class TestReviewerAgent:
    def test_review_all_success(self):
        reviewer = ReviewerAgent()
        ctx = AgentContext(task_id="t1", task_title="Test", task_body="body")
        ctx.execution_results = [
            {"step": 1, "description": "Step 1", "tool": "none", "success": True, "output": "OK", "error": ""},
            {"step": 2, "description": "Step 2", "tool": "none", "success": True, "output": "OK", "error": ""},
        ]
        ctx = reviewer.process(ctx)
        assert ctx.review_verdict == "approved"

    def test_review_all_failed(self):
        reviewer = ReviewerAgent()
        ctx = AgentContext(task_id="t2", task_title="Test", task_body="body")
        ctx.execution_results = [
            {"step": 1, "description": "Step 1", "tool": "email", "success": False, "output": "", "error": "fail"},
        ]
        ctx = reviewer.process(ctx)
        assert ctx.review_verdict == "rejected"

    def test_review_partial(self):
        reviewer = ReviewerAgent()
        ctx = AgentContext(task_id="t3", task_title="Test", task_body="body")
        ctx.execution_results = [
            {"step": 1, "description": "Step 1", "tool": "none", "success": True, "output": "OK", "error": ""},
            {"step": 2, "description": "Step 2", "tool": "email", "success": False, "output": "", "error": "fail"},
        ]
        ctx = reviewer.process(ctx)
        assert ctx.review_verdict == "partial"

    def test_review_no_results(self):
        reviewer = ReviewerAgent()
        ctx = AgentContext(task_id="t4", task_title="Test", task_body="body")
        ctx = reviewer.process(ctx)
        assert ctx.review_verdict == "no_results"


class TestAgentCoordinator:
    def test_full_pipeline(self, tmp_vault, setup_tools):
        coordinator = AgentCoordinator(vault_root=str(tmp_vault))
        ctx = coordinator.run_pipeline(
            task_id="pipeline-test",
            title="Send update email",
            body="Send a weekly update email to the team",
        )
        assert ctx.plan
        assert len(ctx.execution_results) > 0
        assert ctx.review_verdict in ("approved", "partial", "rejected")
        assert len(ctx.messages) > 0

    def test_planning_only(self, tmp_vault, setup_tools):
        coordinator = AgentCoordinator(vault_root=str(tmp_vault))
        ctx = coordinator.run_planning_only(
            task_id="plan-test",
            title="Create report",
            body="Create a file report",
        )
        assert ctx.plan
        assert len(ctx.execution_results) == 0
