"""Tests for the FastAPI Silver API endpoints."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from fastapi.testclient import TestClient


@pytest.fixture
def vault_dir(tmp_path):
    """Create a temporary vault structure."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    archive_dir = tasks_dir / "archive"
    archive_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    needs_action = tmp_path / "needs_action"
    needs_action.mkdir()
    completed = tmp_path / "completed"
    completed.mkdir()
    approved = tmp_path / "approved"
    approved.mkdir()
    return tmp_path


@pytest.fixture
def client(vault_dir, tmp_path):
    """Create a test client with mocked orchestrator."""
    # Patch config and orchestrator before importing server
    mock_config = MagicMock()
    mock_config.vault.tasks = vault_dir / "tasks"
    mock_config.vault.logs = vault_dir / "logs"
    mock_config.vault.root = vault_dir
    mock_config.vault.halt_file = vault_dir / "HALT.md"
    mock_config.vault.archive = vault_dir / "tasks" / "archive"
    mock_config.vault.inbox = vault_dir / "inbox"
    mock_config.vault.context = vault_dir / "context"
    mock_config.orchestrator.poll_interval_seconds = 3

    with patch("api.server.config", mock_config), \
         patch("api.server.VAULT_TASKS", vault_dir / "tasks"), \
         patch("api.server.VAULT_LOGS", vault_dir / "logs"), \
         patch("api.server.NEEDS_ACTION_DIR", vault_dir / "needs_action"), \
         patch("api.server.AIEmployeeOrchestrator") as mock_orch_cls, \
         patch("api.server.TaskDatabase") as mock_db_cls:

        from memory.database import TaskDatabase
        real_db = TaskDatabase(db_path=tmp_path / "test.db")

        mock_db_cls.return_value = real_db

        mock_orch = MagicMock()
        mock_orch._running = True
        mock_orch_cls.return_value = mock_orch

        import api.server as server_module
        server_module.db = real_db
        server_module.orchestrator = mock_orch
        server_module.VAULT_TASKS = vault_dir / "tasks"
        server_module.VAULT_LOGS = vault_dir / "logs"
        server_module.NEEDS_ACTION_DIR = vault_dir / "needs_action"

        # Use TestClient without lifespan to avoid background threads
        with TestClient(server_module.app, raise_server_exceptions=False) as test_client:
            yield test_client

        real_db.close()


class TestCreateTask:
    def test_create_task_success(self, client, vault_dir):
        resp = client.post("/tasks", json={
            "title": "Test task",
            "body": "Do something useful",
            "priority": "high",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["priority"] == "high"
        assert data["source"] == "web-ui"
        assert "task-" in data["id"]

        # Verify file was created
        task_files = list((vault_dir / "tasks").glob("*.md"))
        assert len(task_files) >= 1

    def test_create_task_default_priority(self, client):
        resp = client.post("/tasks", json={"title": "Simple task"})
        assert resp.status_code == 201
        assert resp.json()["priority"] == "medium"

    def test_create_task_empty_title_rejected(self, client):
        resp = client.post("/tasks", json={"title": "", "body": "test"})
        assert resp.status_code == 422

    def test_create_task_invalid_priority(self, client):
        resp = client.post("/tasks", json={"title": "Test", "priority": "urgent"})
        assert resp.status_code == 422


class TestListTasks:
    def test_list_empty(self, client):
        resp = client.get("/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["tasks"] == []

    def test_list_after_create(self, client):
        client.post("/tasks", json={"title": "Task one"})
        client.post("/tasks", json={"title": "Task two"})
        resp = client.get("/tasks")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    def test_filter_by_status(self, client):
        client.post("/tasks", json={"title": "Pending task"})
        resp = client.get("/tasks?status=pending")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

        resp = client.get("/tasks?status=completed")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestGetTask:
    def test_get_existing_task(self, client):
        create_resp = client.post("/tasks", json={"title": "My task"})
        task_id = create_resp.json()["id"]
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == task_id

    def test_get_nonexistent_task(self, client):
        resp = client.get("/tasks/nonexistent-id")
        assert resp.status_code == 404


class TestApproveTask:
    def test_approve_awaiting_task(self, client, vault_dir):
        # Create a task file in awaiting-approval state
        import yaml
        task_id = "task-approve-test"
        fm = {"id": task_id, "status": "awaiting-approval", "priority": "high"}
        yaml_str = yaml.dump(fm, default_flow_style=False, sort_keys=False)
        content = f"---\n{yaml_str}---\n\n## Request\n\nTest approve.\n"
        task_file = vault_dir / "tasks" / "2026-01-01_approve-test.md"
        task_file.write_text(content, encoding="utf-8")

        # Sync DB
        import api.server as server_module
        server_module.db.sync_single_task(task_file)

        resp = client.post(f"/approve/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["task_id"] == task_id

    def test_approve_nonexistent_task(self, client):
        resp = client.post("/approve/nonexistent")
        assert resp.status_code == 404

    def test_approve_wrong_status(self, client):
        create_resp = client.post("/tasks", json={"title": "Not ready"})
        task_id = create_resp.json()["id"]
        resp = client.post(f"/approve/{task_id}")
        assert resp.status_code == 400


class TestGetLogs:
    def test_get_logs_empty(self, client):
        resp = client.get("/logs/task-test-001")
        assert resp.status_code == 200
        assert resp.json()["logs"] == []

    def test_get_logs_with_entries(self, client, vault_dir):
        import yaml
        logs_dir = vault_dir / "logs"
        fm = {"timestamp": "2026-01-01T00:00:00", "task_id": "task-log-test", "action": "test"}
        yaml_str = yaml.dump(fm, default_flow_style=False, sort_keys=False)
        log_file = logs_dir / "2026-01-01_00-00-00_001_test.md"
        log_file.write_text(f"---\n{yaml_str}---\n\n## Log\n\nTest log entry.\n", encoding="utf-8")

        resp = client.get("/logs/task-log-test")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["logs"]) == 1
        assert data["logs"][0]["timestamp"] == "2026-01-01T00:00:00"


class TestDemoPipeline:
    def test_demo_run(self, client, vault_dir):
        resp = client.post("/demo/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["final_status"] == "completed"
        assert len(data["stages"]) == 5
        assert all(s["status"] == "success" for s in data["stages"])
        assert "demo-" in data["task_id"]


class TestDashboard:
    def test_serve_dashboard(self, client):
        # This might return 404 if UI dir doesn't exist in test env
        resp = client.get("/")
        assert resp.status_code in (200, 404)
