"""Tests for Platinum tier monitoring system."""

import pytest
from pathlib import Path
from platinum.monitoring.monitor import (
    MetricsCollector, HealthChecker, HealthCheck, AlertManager, SystemMonitor,
)


class TestMetricsCollector:
    def test_record_and_get(self):
        mc = MetricsCollector()
        mc.record("test.metric", 42.0, unit="ms")
        metrics = mc.get_metrics("test.metric")
        assert len(metrics) == 1
        assert metrics[0]["value"] == 42.0

    def test_counter(self):
        mc = MetricsCollector()
        mc.increment("test.counter")
        mc.increment("test.counter", 5)
        assert mc.get_counter("test.counter") == 6

    def test_gauge(self):
        mc = MetricsCollector()
        mc.set_gauge("test.gauge", 3.14)
        assert mc.get_gauge("test.gauge") == 3.14

    def test_summary(self):
        mc = MetricsCollector()
        mc.increment("a")
        mc.set_gauge("b", 1.0)
        mc.record("c", 2.0)
        summary = mc.get_summary()
        assert "a" in summary["counters"]
        assert "b" in summary["gauges"]
        assert "c" in summary["metric_series"]

    def test_max_history(self):
        mc = MetricsCollector(max_history=5)
        for i in range(10):
            mc.record("test", float(i))
        assert len(mc.get_metrics("test", minutes=9999)) == 5


class TestHealthChecker:
    def test_register_and_run(self):
        hc = HealthChecker()
        hc.register("test", lambda: HealthCheck(name="test", status="healthy"))
        results = hc.run_all()
        assert len(results) == 1
        assert results[0].status == "healthy"

    def test_unhealthy_check(self):
        hc = HealthChecker()
        hc.register("bad", lambda: HealthCheck(name="bad", status="unhealthy", message="down"))
        status = hc.get_status()
        assert status["overall"] == "unhealthy"

    def test_exception_in_check(self):
        hc = HealthChecker()
        def failing_check():
            raise RuntimeError("check failed")
        hc.register("fail", failing_check)
        results = hc.run_all()
        assert results[0].status == "unhealthy"

    def test_mixed_status(self):
        hc = HealthChecker()
        hc.register("ok", lambda: HealthCheck(name="ok", status="healthy"))
        hc.register("meh", lambda: HealthCheck(name="meh", status="degraded"))
        status = hc.get_status()
        assert status["overall"] == "degraded"


class TestAlertManager:
    def test_fire_alert(self, tmp_path):
        am = AlertManager(vault_root=str(tmp_path))
        (tmp_path / "logs").mkdir()
        alert = am.fire("warning", "test", "Something happened")
        assert alert.severity == "warning"
        active = am.get_active_alerts()
        assert len(active) == 1

    def test_acknowledge_alert(self, tmp_path):
        am = AlertManager(vault_root=str(tmp_path))
        (tmp_path / "logs").mkdir()
        alert = am.fire("error", "test", "Error")
        am.acknowledge(alert.id)
        active = am.get_active_alerts()
        assert len(active) == 0

    def test_get_all_alerts(self, tmp_path):
        am = AlertManager(vault_root=str(tmp_path))
        (tmp_path / "logs").mkdir()
        am.fire("info", "a", "msg1")
        am.fire("warning", "b", "msg2")
        all_alerts = am.get_all_alerts()
        assert len(all_alerts) == 2


class TestSystemMonitor:
    def test_dashboard_data(self, tmp_path):
        monitor = SystemMonitor(vault_root=str(tmp_path))
        (tmp_path / "logs").mkdir()

        data = monitor.get_dashboard_data()
        assert "health" in data
        assert "metrics" in data
        assert "alerts" in data
        assert "timestamp" in data

    def test_start_stop(self, tmp_path):
        monitor = SystemMonitor(vault_root=str(tmp_path))
        monitor.start()
        assert monitor._running is True
        monitor.stop()
        assert monitor._running is False
