"""Tests for markdown_parser."""

import pytest
from pathlib import Path
from watchers.utils.markdown_parser import (
    parse_frontmatter,
    validate_frontmatter,
    update_frontmatter,
)


class TestParseFrontmatter:
    def test_parse_valid(self, sample_task_file):
        fm, body = parse_frontmatter(sample_task_file)
        assert fm["id"] == "task-test-001"
        assert fm["status"] == "pending"
        assert fm["priority"] == "high"
        assert "test task" in body.lower()

    def test_parse_no_frontmatter(self, tmp_path):
        f = tmp_path / "plain.md"
        f.write_text("# Just a heading\n\nSome text.", encoding="utf-8")
        fm, body = parse_frontmatter(f)
        assert fm == {}
        assert "Just a heading" in body

    def test_parse_empty_frontmatter(self, tmp_path):
        f = tmp_path / "empty_fm.md"
        f.write_text("---\n---\n\nBody here.", encoding="utf-8")
        fm, body = parse_frontmatter(f)
        assert fm == {}
        assert "Body here" in body

    def test_parse_preserves_body(self, sample_task_file):
        fm, body = parse_frontmatter(sample_task_file)
        assert "## Request" in body
        assert "## Context" in body

    def test_parse_tags_as_list(self, sample_task_file):
        fm, _ = parse_frontmatter(sample_task_file)
        assert isinstance(fm["tags"], list)
        assert "test" in fm["tags"]


class TestValidateFrontmatter:
    def test_valid_frontmatter(self):
        fm = {"id": "task-001", "status": "pending"}
        assert validate_frontmatter(fm) == []

    def test_missing_id(self):
        fm = {"status": "pending"}
        missing = validate_frontmatter(fm)
        assert "id" in missing

    def test_missing_status(self):
        fm = {"id": "task-001"}
        missing = validate_frontmatter(fm)
        assert "status" in missing

    def test_missing_both(self):
        fm = {"priority": "high"}
        missing = validate_frontmatter(fm)
        assert "id" in missing
        assert "status" in missing

    def test_empty_frontmatter(self):
        missing = validate_frontmatter({})
        assert len(missing) == 2


class TestUpdateFrontmatter:
    def test_update_status(self, sample_task_file):
        update_frontmatter(sample_task_file, {"status": "planning"})
        fm, _ = parse_frontmatter(sample_task_file)
        assert fm["status"] == "planning"

    def test_update_preserves_body(self, sample_task_file):
        update_frontmatter(sample_task_file, {"status": "approved"})
        fm, body = parse_frontmatter(sample_task_file)
        assert "## Request" in body
        assert "test task" in body.lower()

    def test_update_adds_new_field(self, sample_task_file):
        update_frontmatter(sample_task_file, {"last_updated": "2026-02-12T15:00:00"})
        fm, _ = parse_frontmatter(sample_task_file)
        assert "last_updated" in fm

    def test_update_preserves_existing_fields(self, sample_task_file):
        update_frontmatter(sample_task_file, {"status": "approved"})
        fm, _ = parse_frontmatter(sample_task_file)
        assert fm["id"] == "task-test-001"
        assert fm["priority"] == "high"
        assert fm["status"] == "approved"
