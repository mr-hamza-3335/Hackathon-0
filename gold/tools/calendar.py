"""Calendar tool — scheduling and event management.

Provides local calendar functionality backed by a JSON file
in the vault. No external calendar service required.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gold.tools.base import BaseTool, ToolResult
from gold.security.permissions import RiskTier

logger = logging.getLogger("gold.tools.calendar")


class CalendarTool(BaseTool):
    """Local calendar scheduling tool."""

    def __init__(self, vault_root: str = "./vault") -> None:
        self.vault_root = Path(vault_root)
        self.calendar_file = self.vault_root / "calendar.json"
        self._ensure_calendar()

    def _ensure_calendar(self) -> None:
        if not self.calendar_file.exists():
            self.calendar_file.write_text("[]", encoding="utf-8")

    def _load_events(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.calendar_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_events(self, events: list[dict[str, Any]]) -> None:
        self.calendar_file.write_text(
            json.dumps(events, indent=2, default=str), encoding="utf-8"
        )

    @property
    def name(self) -> str:
        return "calendar"

    @property
    def description(self) -> str:
        return "Local calendar scheduling and event management"

    @property
    def actions(self) -> dict[str, str]:
        return {
            "schedule_event": "Schedule a new calendar event",
            "get_calendar": "List upcoming events",
            "cancel_event": "Cancel a scheduled event",
        }

    def get_risk_tier(self, action: str) -> RiskTier:
        tiers = {
            "get_calendar": RiskTier.T0,
            "schedule_event": RiskTier.T1,
            "cancel_event": RiskTier.T1,
        }
        return tiers.get(action, RiskTier.T2)

    def execute(self, action: str, params: dict[str, Any]) -> ToolResult:
        handlers = {
            "schedule_event": self._schedule_event,
            "get_calendar": self._get_calendar,
            "cancel_event": self._cancel_event,
        }
        handler = handlers.get(action)
        if not handler:
            return ToolResult(tool=self.name, action=action, success=False,
                            error=f"Unknown action: {action}", output=None)
        return handler(params)

    def _schedule_event(self, params: dict[str, Any]) -> ToolResult:
        title = params.get("title", "")
        date = params.get("date", "")
        time_str = params.get("time", "")
        duration_minutes = params.get("duration_minutes", 60)
        description = params.get("description", "")

        if not title or not date:
            return ToolResult(tool=self.name, action="schedule_event", success=False,
                            error="'title' and 'date' are required", output=None)

        events = self._load_events()
        event = {
            "id": f"evt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "title": title,
            "date": date,
            "time": time_str or "09:00",
            "duration_minutes": duration_minutes,
            "description": description,
            "status": "scheduled",
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        events.append(event)
        self._save_events(events)

        logger.info(f"Event scheduled: {title} on {date}")
        return ToolResult(tool=self.name, action="schedule_event", success=True,
                        output=event)

    def _get_calendar(self, params: dict[str, Any]) -> ToolResult:
        events = self._load_events()
        active = [e for e in events if e.get("status") != "cancelled"]

        # Filter by date range if provided
        from_date = params.get("from_date")
        to_date = params.get("to_date")
        if from_date:
            active = [e for e in active if e.get("date", "") >= from_date]
        if to_date:
            active = [e for e in active if e.get("date", "") <= to_date]

        return ToolResult(tool=self.name, action="get_calendar", success=True,
                        output={"events": active, "count": len(active)})

    def _cancel_event(self, params: dict[str, Any]) -> ToolResult:
        event_id = params.get("event_id", "")
        if not event_id:
            return ToolResult(tool=self.name, action="cancel_event", success=False,
                            error="'event_id' is required", output=None)

        events = self._load_events()
        for event in events:
            if event.get("id") == event_id:
                event["status"] = "cancelled"
                self._save_events(events)
                return ToolResult(tool=self.name, action="cancel_event", success=True,
                                output={"cancelled": event_id})

        return ToolResult(tool=self.name, action="cancel_event", success=False,
                        error=f"Event {event_id} not found", output=None)
