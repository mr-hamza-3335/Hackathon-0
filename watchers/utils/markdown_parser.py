"""Parse YAML frontmatter from markdown task files."""

from pathlib import Path
from typing import Any
import yaml


REQUIRED_FIELDS = {"id", "status"}


def parse_frontmatter(file_path: Path) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and body from a markdown file.

    Returns:
        Tuple of (frontmatter_dict, body_string).
        Returns empty dict if no frontmatter found.
    """
    text = file_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return frontmatter, body


def validate_frontmatter(frontmatter: dict[str, Any]) -> list[str]:
    """Validate that required fields are present.

    Returns:
        List of missing field names. Empty list means valid.
    """
    missing = REQUIRED_FIELDS - set(frontmatter.keys())
    return sorted(missing)


def update_frontmatter(file_path: Path, updates: dict[str, Any]) -> None:
    """Update specific fields in a file's YAML frontmatter."""
    frontmatter, body = parse_frontmatter(file_path)
    frontmatter.update(updates)
    yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    new_content = f"---\n{yaml_str}---\n\n{body}\n"
    file_path.write_text(new_content, encoding="utf-8")
