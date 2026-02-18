"""Multi-agent base — Gold tier agent abstraction.

Defines the base agent interface and agent coordination system.
Each agent (Planner, Executor, Reviewer) logs its reasoning.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("gold.agents")


@dataclass
class AgentMessage:
    """A message in the agent reasoning chain."""
    agent: str
    role: str  # "input", "reasoning", "output", "error"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    """Shared context passed between agents."""
    task_id: str
    task_title: str
    task_body: str
    messages: list[AgentMessage] = field(default_factory=list)
    plan: str = ""
    execution_results: list[dict[str, Any]] = field(default_factory=list)
    review_verdict: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, agent: str, role: str, content: str, **kwargs: Any) -> None:
        self.messages.append(AgentMessage(
            agent=agent, role=role, content=content, metadata=kwargs,
        ))

    def get_reasoning_log(self) -> str:
        """Get a formatted log of all agent reasoning."""
        lines = []
        for msg in self.messages:
            lines.append(f"[{msg.timestamp}] {msg.agent} ({msg.role}): {msg.content[:200]}")
        return "\n".join(lines)


class BaseAgent(ABC):
    """Abstract base for all AI agents."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def role(self) -> str:
        ...

    @abstractmethod
    def process(self, context: AgentContext) -> AgentContext:
        """Process the context and return updated context."""
        ...

    def log_reasoning(self, context: AgentContext, reasoning: str) -> None:
        """Log agent reasoning to the context."""
        context.add_message(self.name, "reasoning", reasoning)
        logger.info(f"[{self.name}] {reasoning[:100]}")
