"""Advanced Monitoring — Platinum tier.

Provides:
- System metrics collection
- Health checks
- Error alerts
- Performance tracking
"""

import logging
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("platinum.monitoring")


@dataclass
class Metric:
    """A single metric data point."""
    name: str
    value: float
    unit: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class HealthCheck:
    """A health check result."""
    name: str
    status: str  # "healthy", "degraded", "unhealthy"
    message: str = ""
    latency_ms: float = 0
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Alert:
    """An error alert."""
    id: str
    severity: str  # "info", "warning", "error", "critical"
    source: str
    message: str
    details: str = ""
    acknowledged: bool = False
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MetricsCollector:
    """Collects and stores system metrics."""

    def __init__(self, max_history: int = 1000) -> None:
        self._metrics: dict[str, list[Metric]] = defaultdict(list)
        self._max_history = max_history
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}

    def record(self, name: str, value: float, unit: str = "",
              tags: dict[str, str] | None = None) -> None:
        """Record a metric value."""
        metric = Metric(name=name, value=value, unit=unit, tags=tags or {})
        self._metrics[name].append(metric)

        # Trim history
        if len(self._metrics[name]) > self._max_history:
            self._metrics[name] = self._metrics[name][-self._max_history:]

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment a counter."""
        self._counters[name] += amount

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge value."""
        self._gauges[name] = value

    def get_counter(self, name: str) -> int:
        return self._counters.get(name, 0)

    def get_gauge(self, name: str) -> float | None:
        return self._gauges.get(name)

    def get_metrics(self, name: str, minutes: int = 60) -> list[dict[str, Any]]:
        """Get metric history for the last N minutes."""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        return [
            {"value": m.value, "unit": m.unit, "tags": m.tags, "timestamp": m.timestamp}
            for m in self._metrics.get(name, [])
            if m.timestamp >= cutoff
        ]

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all metrics."""
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "metric_series": {k: len(v) for k, v in self._metrics.items()},
        }


class HealthChecker:
    """Runs health checks on system components."""

    def __init__(self) -> None:
        self._checks: dict[str, Callable[[], HealthCheck]] = {}
        self._last_results: dict[str, HealthCheck] = {}

    def register(self, name: str, check_fn: Callable[[], HealthCheck]) -> None:
        """Register a health check."""
        self._checks[name] = check_fn

    def run_all(self) -> list[HealthCheck]:
        """Run all registered health checks."""
        results = []
        for name, check_fn in self._checks.items():
            start = time.time()
            try:
                result = check_fn()
                result.latency_ms = (time.time() - start) * 1000
            except Exception as e:
                result = HealthCheck(
                    name=name, status="unhealthy",
                    message=str(e),
                    latency_ms=(time.time() - start) * 1000,
                )
            self._last_results[name] = result
            results.append(result)
        return results

    def get_status(self) -> dict[str, Any]:
        """Get overall system health status."""
        results = self.run_all()
        statuses = [r.status for r in results]

        if all(s == "healthy" for s in statuses):
            overall = "healthy"
        elif any(s == "unhealthy" for s in statuses):
            overall = "unhealthy"
        else:
            overall = "degraded"

        return {
            "overall": overall,
            "checks": [
                {
                    "name": r.name,
                    "status": r.status,
                    "message": r.message,
                    "latency_ms": round(r.latency_ms, 2),
                    "checked_at": r.checked_at,
                }
                for r in results
            ],
        }


class AlertManager:
    """Manages system alerts."""

    def __init__(self, vault_root: str = "./vault") -> None:
        self._alerts: list[Alert] = []
        self.vault_root = Path(vault_root)
        self._alert_counter = 0

    def fire(self, severity: str, source: str, message: str,
            details: str = "") -> Alert:
        """Fire a new alert."""
        self._alert_counter += 1
        alert = Alert(
            id=f"alert-{self._alert_counter:04d}",
            severity=severity,
            source=source,
            message=message,
            details=details,
        )
        self._alerts.append(alert)
        logger.warning(f"Alert [{severity}] {source}: {message}")

        # Write to vault for visibility
        self._write_alert_file(alert)
        return alert

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        for alert in self._alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                return True
        return False

    def get_active_alerts(self) -> list[dict[str, Any]]:
        """Get all unacknowledged alerts."""
        return [
            {
                "id": a.id,
                "severity": a.severity,
                "source": a.source,
                "message": a.message,
                "created": a.created,
            }
            for a in self._alerts
            if not a.acknowledged
        ]

    def get_all_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get all alerts (most recent first)."""
        return [
            {
                "id": a.id,
                "severity": a.severity,
                "source": a.source,
                "message": a.message,
                "details": a.details,
                "acknowledged": a.acknowledged,
                "created": a.created,
            }
            for a in reversed(self._alerts[-limit:])
        ]

    def _write_alert_file(self, alert: Alert) -> None:
        """Write alert to a file in vault/logs/ for visibility."""
        logs_dir = self.vault_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')}_alert_{alert.id}.md"
        content = f"""---
type: alert
alert_id: {alert.id}
severity: {alert.severity}
source: {alert.source}
timestamp: {alert.created}
---

# Alert: {alert.message}

**Severity:** {alert.severity}
**Source:** {alert.source}

{alert.details}
"""
        (logs_dir / filename).write_text(content, encoding="utf-8")


class SystemMonitor:
    """Central monitoring system that ties everything together."""

    def __init__(self, vault_root: str = "./vault") -> None:
        self.metrics = MetricsCollector()
        self.health = HealthChecker()
        self.alerts = AlertManager(vault_root=vault_root)
        self._monitor_thread: threading.Thread | None = None
        self._running = False

        # Register default health checks
        self._register_defaults(vault_root)

    def _register_defaults(self, vault_root: str) -> None:
        """Register default health checks."""
        vault_path = Path(vault_root)

        def check_vault():
            if vault_path.exists():
                return HealthCheck(name="vault", status="healthy", message="Vault directory exists")
            return HealthCheck(name="vault", status="unhealthy", message="Vault directory missing")

        def check_database():
            db_path = Path("silver.db")
            if db_path.exists():
                size_mb = db_path.stat().st_size / (1024 * 1024)
                return HealthCheck(name="database", status="healthy",
                                 message=f"Database OK ({size_mb:.1f} MB)")
            return HealthCheck(name="database", status="degraded", message="Database not found")

        def check_disk():
            import shutil
            total, used, free = shutil.disk_usage(".")
            free_gb = free / (1024**3)
            if free_gb > 1:
                return HealthCheck(name="disk", status="healthy",
                                 message=f"{free_gb:.1f} GB free")
            return HealthCheck(name="disk", status="degraded",
                             message=f"Low disk: {free_gb:.1f} GB free")

        self.health.register("vault", check_vault)
        self.health.register("database", check_database)
        self.health.register("disk", check_disk)

    def start(self) -> None:
        """Start background monitoring."""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="system-monitor",
        )
        self._monitor_thread.start()
        logger.info("System monitor started")

    def stop(self) -> None:
        """Stop background monitoring."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)

    def _monitor_loop(self) -> None:
        """Background monitoring loop — collects metrics every 30s."""
        while self._running:
            try:
                # Collect system metrics
                import os
                self.metrics.set_gauge("process.threads", threading.active_count())

                # Run health checks
                results = self.health.run_all()
                for r in results:
                    if r.status == "unhealthy":
                        self.alerts.fire("error", r.name, f"Health check failed: {r.message}")

                self.metrics.increment("monitoring.cycles")
            except Exception as e:
                logger.debug(f"Monitor error: {e}")

            time.sleep(30)

    def get_dashboard_data(self) -> dict[str, Any]:
        """Get all monitoring data for the dashboard."""
        return {
            "health": self.health.get_status(),
            "metrics": self.metrics.get_summary(),
            "alerts": self.alerts.get_active_alerts(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Singleton
monitor = SystemMonitor()
