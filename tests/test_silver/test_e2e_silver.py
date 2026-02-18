"""End-to-end test for the full Silver pipeline via API."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

import yaml
from fastapi.testclient import TestClient


@pytest.fixture
def vault_dir(tmp_path):
    """Create a full temporary vault structure."""
    for subdir in ("tasks", "tasks/archive", "logs", "needs_action",
                    "completed", "approved", "inbox", "context"):
        (tmp_path / subdir).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def client(vault_dir, tmp_path):
    """Create a test client with mocked orchestrator."""
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
         patch("api.server.AIEmployeeOrchestrator") as mock_orch_cls:

        from memory.database import TaskDatabase
        real_db = TaskDatabase(db_path=tmp_path / "e2e_test.db")

        mock_orch = MagicMock()
        mock_orch._running = True
        mock_orch_cls.return_value = mock_orch

        import api.server as server_module
        server_module.db = real_db
        server_module.orchestrator = mock_orch
        server_module.VAULT_TASKS = vault_dir / "tasks"
        server_module.VAULT_LOGS = vault_dir / "logs"
        server_module.NEEDS_ACTION_DIR = vault_dir / "needs_action"

        with TestClient(server_module.app, raise_server_exceptions=False) as test_client:
            yield test_client

        real_db.close()


class TestFullPipeline:
    """Test the complete Silver pipeline: create → list → simulate plan → approve → verify."""

    def test_create_list_approve_flow(self, client, vault_dir):
        # 1. Create a task via API
        resp = client.post("/tasks", json={
            "title": "E2E Test Task",
            "body": "Full pipeline test",
            "priority": "high",
        })
        assert resp.status_code == 201
        task_id = resp.json()["id"]

        # 2. Verify it appears in task list
        resp = client.get("/tasks")
        assert resp.status_code == 200
        tasks = resp.json()["tasks"]
        assert any(t["id"] == task_id for t in tasks)

        # 3. Verify the file was written to vault
        task_files = list((vault_dir / "tasks").glob("*.md"))
        assert len(task_files) >= 1
        task_file = next(f for f in task_files if task_id in f.read_text())

        # 4. Simulate orchestrator planning (update file to awaiting-approval)
        from watchers.utils.markdown_parser import parse_frontmatter, update_frontmatter
        fm, body = parse_frontmatter(task_file)
        fm["status"] = "awaiting-approval"
        plan = body + "\n\n## Proposed Plan\n\n- [ ] Step 1: Do thing (tool: none, approval: no)\n"
        yaml_str = yaml.dump(fm, default_flow_style=False, sort_keys=False)
        task_file.write_text(f"---\n{yaml_str}---\n\n{plan}\n", encoding="utf-8")

        # 5. Verify task shows as awaiting-approval
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "awaiting-approval"

        # 6. Approve the task via API
        resp = client.post(f"/approve/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        # 7. Verify task is now approved in DB
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        # 8. Verify the file frontmatter was updated
        fm_after, _ = parse_frontmatter(task_file)
        assert fm_after["status"] == "approved"

    def test_demo_pipeline_full(self, client, vault_dir):
        # Run demo pipeline
        resp = client.post("/demo/run")
        assert resp.status_code == 200
        data = resp.json()

        # Verify all stages passed
        assert data["final_status"] == "completed"
        stages = {s["stage"]: s["status"] for s in data["stages"]}
        assert stages["create"] == "success"
        assert stages["plan"] == "success"
        assert stages["approve"] == "success"
        assert stages["execute"] == "success"
        assert stages["archive"] == "success"

        # Verify task was archived
        archived = list((vault_dir / "tasks" / "archive").glob("*demo*"))
        assert len(archived) >= 1

        # Verify task is in DB as completed
        resp = client.get(f"/tasks/{data['task_id']}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_multiple_tasks_lifecycle(self, client, vault_dir):
        # Create multiple tasks
        ids = []
        for i in range(3):
            resp = client.post("/tasks", json={"title": f"Task {i+1}"})
            assert resp.status_code == 201
            ids.append(resp.json()["id"])

        # Verify all appear
        resp = client.get("/tasks")
        assert resp.json()["count"] >= 3

        # Filter by status
        resp = client.get("/tasks?status=pending")
        assert resp.json()["count"] >= 3
