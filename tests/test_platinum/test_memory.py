"""Tests for Platinum tier persistent memory system."""

import pytest
from pathlib import Path
from platinum.memory.memory_store import MemoryStore


@pytest.fixture
def memory(tmp_path):
    db_path = str(tmp_path / "test_memory.db")
    store = MemoryStore(db_path=db_path)
    yield store
    store.close()


class TestMemoryStore:
    def test_store_and_recall(self, memory):
        memory.store("preferences", "theme", "dark", tags=["ui"])
        results = memory.recall(category="preferences")
        assert len(results) == 1
        assert results[0]["key"] == "theme"
        assert results[0]["value"] == "dark"

    def test_recall_by_tags(self, memory):
        memory.store("notes", "note1", "first", tags=["important"])
        memory.store("notes", "note2", "second", tags=["trivial"])
        results = memory.recall(tags=["important"])
        assert len(results) == 1
        assert results[0]["key"] == "note1"

    def test_search(self, memory):
        memory.store("facts", "python", "Python is great", tags=["programming"])
        results = memory.search("Python")
        assert len(results) >= 1

    def test_forget(self, memory):
        mid = memory.store("temp", "key", "value")
        assert memory.forget(mid) is True
        results = memory.recall(category="temp")
        assert len(results) == 0

    def test_access_count(self, memory):
        memory.store("test", "key", "value")
        memory.recall(category="test")  # access 1
        memory.recall(category="test")  # access 2
        memory.recall(category="test")  # access 3
        # access_count is read before increment in the same query,
        # so the returned value reflects the state before this call's update
        results = memory.recall(category="test")  # access 4
        assert results[0]["access_count"] >= 3


class TestTaskHistory:
    def test_record_and_get(self, memory):
        memory.record_task("t1", "Test Task", "completed", plan="plan", verdict="approved")
        history = memory.get_task_history(task_id="t1")
        assert len(history) == 1
        assert history[0]["title"] == "Test Task"
        assert history[0]["status"] == "completed"

    def test_filter_by_status(self, memory):
        memory.record_task("t1", "Task 1", "completed")
        memory.record_task("t2", "Task 2", "failed")
        history = memory.get_task_history(status="completed")
        assert len(history) == 1

    def test_search_history(self, memory):
        memory.record_task("t1", "Send weekly report", "completed")
        results = memory.search_task_history("weekly")
        assert len(results) == 1


class TestContextEntries:
    def test_store_and_recall(self, memory):
        memory.store_context("user", "User prefers dark mode", tags=["preference"])
        results = memory.recall_context(tags=["preference"])
        assert len(results) == 1
        assert "dark mode" in results[0]["content"]

    def test_recall_by_source(self, memory):
        memory.store_context("system", "System config loaded")
        memory.store_context("user", "User said hello")
        results = memory.recall_context(source="user")
        assert len(results) == 1


class TestDecisions:
    def test_record_and_get(self, memory):
        memory.record_decision(
            "Used template plan",
            reasoning="AI unavailable",
            outcome="success",
            task_id="t1",
        )
        decisions = memory.get_decisions(task_id="t1")
        assert len(decisions) == 1
        assert decisions[0]["decision"] == "Used template plan"


class TestStats:
    def test_get_stats(self, memory):
        memory.store("cat", "key", "val")
        memory.record_task("t1", "Task", "completed")
        stats = memory.get_stats()
        assert stats["memories"] == 1
        assert stats["task_history"] == 1
