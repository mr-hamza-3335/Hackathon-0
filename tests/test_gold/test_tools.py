"""Tests for Gold tier tools (filesystem, email, shell, calendar)."""

import json
import pytest
from pathlib import Path
from gold.tools.base import ToolRegistry, ToolExecutor, ToolResult
from gold.tools.filesystem import FilesystemTool
from gold.tools.email import EmailTool
from gold.tools.shell import ShellTool
from gold.tools.calendar import CalendarTool


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a temporary vault structure."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "drafts").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "output").mkdir()
    return tmp_path


class TestFilesystemTool:
    def test_create_and_read_file(self, tmp_vault):
        tool = FilesystemTool(vault_root=str(tmp_vault))

        # Create
        result = tool.execute("create_file", {
            "path": str(tmp_vault / "output" / "test.txt"),
            "content": "Hello, World!",
        })
        assert result.success is True
        assert result.output["size"] == 13

        # Read
        result = tool.execute("read_file", {
            "path": str(tmp_vault / "output" / "test.txt"),
        })
        assert result.success is True
        assert result.output["content"] == "Hello, World!"

    def test_list_files(self, tmp_vault):
        # Create some files
        (tmp_vault / "test1.md").write_text("a", encoding="utf-8")
        (tmp_vault / "test2.md").write_text("b", encoding="utf-8")

        tool = FilesystemTool(vault_root=str(tmp_vault))
        result = tool.execute("list_files", {"path": str(tmp_vault), "pattern": "*.md"})
        assert result.success is True
        assert result.output["count"] == 2

    def test_search_files(self, tmp_vault):
        (tmp_vault / "tasks" / "task1.md").write_text("a", encoding="utf-8")
        tool = FilesystemTool(vault_root=str(tmp_vault))
        result = tool.execute("search_files", {"path": str(tmp_vault), "pattern": "*.md"})
        assert result.success is True
        assert result.output["count"] >= 1

    def test_delete_file(self, tmp_vault):
        file_path = tmp_vault / "output" / "delete_me.txt"
        file_path.parent.mkdir(exist_ok=True)
        file_path.write_text("bye", encoding="utf-8")

        tool = FilesystemTool(vault_root=str(tmp_vault))
        result = tool.execute("delete_file", {"path": str(file_path)})
        assert result.success is True
        assert not file_path.exists()

    def test_read_nonexistent(self, tmp_vault):
        tool = FilesystemTool(vault_root=str(tmp_vault))
        result = tool.execute("read_file", {"path": str(tmp_vault / "nope.txt")})
        assert result.success is False


class TestEmailTool:
    def test_draft_email(self, tmp_vault):
        tool = EmailTool(vault_root=str(tmp_vault))
        result = tool.execute("draft_email", {
            "to": "test@example.com",
            "subject": "Test",
            "body": "Hello",
        })
        assert result.success is True
        assert result.output["to"] == "test@example.com"

    def test_send_email(self, tmp_vault):
        tool = EmailTool(vault_root=str(tmp_vault))
        result = tool.execute("send_email", {
            "to": "test@example.com",
            "subject": "Test",
            "body": "Hello",
        })
        assert result.success is True
        assert result.output["mode"] == "simulated"
        assert "message_id" in result.output

    def test_list_drafts(self, tmp_vault):
        tool = EmailTool(vault_root=str(tmp_vault))
        # Create a draft first
        tool.execute("draft_email", {"to": "a@b.com", "subject": "X", "body": "Y"})
        result = tool.execute("list_drafts", {})
        assert result.success is True
        assert result.output["count"] >= 1

    def test_missing_required_fields(self, tmp_vault):
        tool = EmailTool(vault_root=str(tmp_vault))
        result = tool.execute("draft_email", {"body": "no to/subject"})
        assert result.success is False


class TestShellTool:
    def test_safe_command(self):
        tool = ShellTool()
        result = tool.execute("shell_command", {"command": "echo hello"})
        assert result.success is True
        assert "hello" in result.output["stdout"]

    def test_blocked_command(self):
        tool = ShellTool()
        result = tool.execute("shell_command", {"command": "rm -rf /"})
        assert result.success is False
        assert "blocked" in result.error.lower()

    def test_empty_command(self):
        tool = ShellTool()
        result = tool.execute("shell_command", {"command": ""})
        assert result.success is False

    def test_unknown_action(self):
        tool = ShellTool()
        result = tool.execute("unknown_action", {})
        assert result.success is False


class TestCalendarTool:
    def test_schedule_and_get(self, tmp_vault):
        tool = CalendarTool(vault_root=str(tmp_vault))

        # Schedule
        result = tool.execute("schedule_event", {
            "title": "Team Meeting",
            "date": "2026-02-20",
            "time": "14:00",
            "duration_minutes": 30,
        })
        assert result.success is True
        event_id = result.output["id"]

        # Get calendar
        result = tool.execute("get_calendar", {})
        assert result.success is True
        assert result.output["count"] == 1

    def test_cancel_event(self, tmp_vault):
        tool = CalendarTool(vault_root=str(tmp_vault))

        # Schedule
        result = tool.execute("schedule_event", {
            "title": "Cancel Me",
            "date": "2026-02-20",
        })
        event_id = result.output["id"]

        # Cancel
        result = tool.execute("cancel_event", {"event_id": event_id})
        assert result.success is True

        # Verify cancelled
        result = tool.execute("get_calendar", {})
        assert result.output["count"] == 0

    def test_missing_required(self, tmp_vault):
        tool = CalendarTool(vault_root=str(tmp_vault))
        result = tool.execute("schedule_event", {"time": "10:00"})
        assert result.success is False


class TestToolRegistry:
    def test_register_and_list(self, tmp_vault):
        registry = ToolRegistry()
        tool = FilesystemTool(vault_root=str(tmp_vault))
        registry.register(tool)

        tools = registry.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "filesystem"

    def test_get_tool(self, tmp_vault):
        registry = ToolRegistry()
        tool = FilesystemTool(vault_root=str(tmp_vault))
        registry.register(tool)

        found = registry.get("filesystem")
        assert found is not None
        assert found.name == "filesystem"

    def test_unregister(self, tmp_vault):
        registry = ToolRegistry()
        tool = FilesystemTool(vault_root=str(tmp_vault))
        registry.register(tool)
        registry.unregister("filesystem")
        assert registry.get("filesystem") is None
