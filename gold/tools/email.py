"""Email tool — safe email operations (mock/draft mode).

Provides email drafting and simulated sending.
In Gold tier, actual sending is mocked for safety.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gold.tools.base import BaseTool, ToolResult
from gold.security.permissions import RiskTier

logger = logging.getLogger("gold.tools.email")


class EmailTool(BaseTool):
    """Safe email operations with drafting and mock sending."""

    def __init__(self, vault_root: str = "./vault") -> None:
        self.vault_root = Path(vault_root)
        self.drafts_dir = self.vault_root / "drafts"
        self.drafts_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "email"

    @property
    def description(self) -> str:
        return "Email drafting and sending (mock-safe in Gold tier)"

    @property
    def actions(self) -> dict[str, str]:
        return {
            "draft_email": "Draft an email and save to vault/drafts/",
            "send_email": "Send an email (simulated — saves draft with sent status)",
            "list_drafts": "List all email drafts",
            "bulk_email": "Send to multiple recipients (simulated, high-risk)",
        }

    def get_risk_tier(self, action: str) -> RiskTier:
        tiers = {
            "draft_email": RiskTier.T1,
            "send_email": RiskTier.T2,
            "list_drafts": RiskTier.T0,
            "bulk_email": RiskTier.T3,
        }
        return tiers.get(action, RiskTier.T3)

    def execute(self, action: str, params: dict[str, Any]) -> ToolResult:
        handlers = {
            "draft_email": self._draft_email,
            "send_email": self._send_email,
            "list_drafts": self._list_drafts,
            "bulk_email": self._bulk_email,
        }
        handler = handlers.get(action)
        if not handler:
            return ToolResult(tool=self.name, action=action, success=False,
                            error=f"Unknown action: {action}", output=None)
        return handler(params)

    def _draft_email(self, params: dict[str, Any]) -> ToolResult:
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")

        if not to or not subject:
            return ToolResult(tool=self.name, action="draft_email", success=False,
                            error="'to' and 'subject' are required", output=None)

        now = datetime.now(timezone.utc)
        filename = f"draft_{now.strftime('%Y%m%d_%H%M%S')}.md"
        draft_path = self.drafts_dir / filename

        content = f"""---
type: email-draft
to: {to}
subject: "{subject}"
status: draft
created: {now.isoformat(timespec='seconds')}
---

{body}
"""
        draft_path.write_text(content, encoding="utf-8")
        logger.info(f"Email draft saved: {filename}")

        return ToolResult(tool=self.name, action="draft_email", success=True,
                        output={"file": str(draft_path), "to": to, "subject": subject})

    def _send_email(self, params: dict[str, Any]) -> ToolResult:
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")

        if not to or not subject:
            return ToolResult(tool=self.name, action="send_email", success=False,
                            error="'to' and 'subject' are required", output=None)

        now = datetime.now(timezone.utc)
        message_id = f"msg-{now.strftime('%Y%m%d%H%M%S')}"
        filename = f"sent_{now.strftime('%Y%m%d_%H%M%S')}.md"
        draft_path = self.drafts_dir / filename

        content = f"""---
type: email-sent
to: {to}
subject: "{subject}"
status: sent
message_id: {message_id}
sent_at: {now.isoformat(timespec='seconds')}
mode: simulated
---

{body}

---
*Sent via AI Employee (Gold tier — simulated)*
"""
        draft_path.write_text(content, encoding="utf-8")
        logger.info(f"Email sent (simulated): {filename} → {to}")

        return ToolResult(tool=self.name, action="send_email", success=True,
                        output={"message_id": message_id, "file": str(draft_path),
                                "to": to, "mode": "simulated"})

    def _list_drafts(self, params: dict[str, Any]) -> ToolResult:
        drafts = []
        for f in sorted(self.drafts_dir.glob("*.md")):
            drafts.append({"filename": f.name, "size": f.stat().st_size})
        return ToolResult(tool=self.name, action="list_drafts", success=True,
                        output={"drafts": drafts, "count": len(drafts)})

    def _bulk_email(self, params: dict[str, Any]) -> ToolResult:
        recipients = params.get("recipients", [])
        subject = params.get("subject", "")
        body = params.get("body", "")

        if not recipients or not subject:
            return ToolResult(tool=self.name, action="bulk_email", success=False,
                            error="'recipients' and 'subject' are required", output=None)

        results = []
        for to in recipients:
            result = self._send_email({"to": to, "subject": subject, "body": body})
            results.append({"to": to, "success": result.success})

        return ToolResult(tool=self.name, action="bulk_email", success=True,
                        output={"sent": len(results), "results": results})
