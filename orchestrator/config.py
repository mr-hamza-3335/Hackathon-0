"""Orchestrator configuration loader.

Loads settings from config.yaml and environment variables.
Environment variables override YAML values.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import os
import yaml
from dotenv import load_dotenv

load_dotenv()

_CONFIG_FILE = Path(__file__).parent / "config.yaml"


@dataclass
class VaultConfig:
    root: Path
    inbox: Path
    tasks: Path
    logs: Path
    context: Path
    halt_file: Path
    archive: Path = field(init=False)

    def __post_init__(self) -> None:
        for attr in ("root", "inbox", "tasks", "logs", "context", "halt_file"):
            val = getattr(self, attr)
            if isinstance(val, str):
                setattr(self, attr, Path(val))
        self.archive = self.tasks / "archive"


@dataclass
class OrchestratorConfig:
    poll_interval_seconds: int = 3
    max_retries: int = 1
    retry_delay_seconds: int = 30
    max_actions_per_hour: int = 10


@dataclass
class ClaudeConfig:
    max_tokens: int = 4096
    temperature: float = 0.3


@dataclass
class ApprovalConfig:
    require_for_tiers: list[str] = field(default_factory=lambda: ["T2", "T3", "T4"])
    poll_interval_seconds: int = 2
    timeout_minutes: int = 60


@dataclass
class AppConfig:
    vault: VaultConfig
    orchestrator: OrchestratorConfig
    claude: ClaudeConfig
    approval: ApprovalConfig


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """Override YAML config values with environment variables."""
    vault_root = os.getenv("VAULT_ROOT")
    if vault_root:
        raw.setdefault("vault", {})["root"] = vault_root
        raw["vault"]["inbox"] = f"{vault_root}/inbox"
        raw["vault"]["tasks"] = f"{vault_root}/tasks"
        raw["vault"]["logs"] = f"{vault_root}/logs"
        raw["vault"]["context"] = f"{vault_root}/context"
        raw["vault"]["halt_file"] = f"{vault_root}/HALT.md"

    poll = os.getenv("ORCHESTRATOR_POLL_INTERVAL")
    if poll:
        raw.setdefault("orchestrator", {})["poll_interval_seconds"] = int(poll)

    return raw


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load configuration from YAML file with env overrides."""
    path = config_path or _CONFIG_FILE

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    raw = _apply_env_overrides(raw)

    vault_cfg = VaultConfig(**raw.get("vault", {}))
    orch_cfg = OrchestratorConfig(**raw.get("orchestrator", {}))
    claude_cfg = ClaudeConfig(**raw.get("claude", {}))
    approval_cfg = ApprovalConfig(**raw.get("approval", {}))

    return AppConfig(
        vault=vault_cfg,
        orchestrator=orch_cfg,
        claude=claude_cfg,
        approval=approval_cfg,
    )


# Singleton
config = load_config()
