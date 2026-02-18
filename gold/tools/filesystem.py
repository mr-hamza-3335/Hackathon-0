"""Filesystem tool — safe file operations.

Provides read, write, list, and search operations on the vault
and designated output directories, enforced by the sandbox.
"""

import logging
from pathlib import Path
from typing import Any

from gold.tools.base import BaseTool, ToolResult
from gold.security.permissions import RiskTier, Sandbox

logger = logging.getLogger("gold.tools.filesystem")


class FilesystemTool(BaseTool):
    """Safe filesystem operations within sandboxed boundaries."""

    def __init__(self, vault_root: str = "./vault") -> None:
        self.vault_root = Path(vault_root)
        self._sandbox = Sandbox(vault_root=vault_root)

    @property
    def name(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return "Safe file operations within the vault directory"

    @property
    def actions(self) -> dict[str, str]:
        return {
            "read_file": "Read contents of a file",
            "create_file": "Create a new file",
            "modify_file": "Modify an existing file",
            "list_files": "List files in a directory",
            "search_files": "Search files by name pattern",
            "delete_file": "Delete a file",
        }

    def get_risk_tier(self, action: str) -> RiskTier:
        tiers = {
            "read_file": RiskTier.T0,
            "list_files": RiskTier.T0,
            "search_files": RiskTier.T0,
            "create_file": RiskTier.T1,
            "modify_file": RiskTier.T2,
            "delete_file": RiskTier.T2,
        }
        return tiers.get(action, RiskTier.T3)

    def execute(self, action: str, params: dict[str, Any]) -> ToolResult:
        """Execute a filesystem action."""
        handlers = {
            "read_file": self._read_file,
            "create_file": self._create_file,
            "modify_file": self._modify_file,
            "list_files": self._list_files,
            "search_files": self._search_files,
            "delete_file": self._delete_file,
        }

        handler = handlers.get(action)
        if not handler:
            return ToolResult(tool=self.name, action=action, success=False,
                            error=f"Unknown action: {action}")

        return handler(params)

    def _read_file(self, params: dict[str, Any]) -> ToolResult:
        path = params.get("path", "")
        valid, reason = self._sandbox.validate_path(path)
        if not valid:
            return ToolResult(tool=self.name, action="read_file",
                            success=False, error=reason, output=None)

        file_path = Path(path)
        if not file_path.exists():
            return ToolResult(tool=self.name, action="read_file",
                            success=False, error=f"File not found: {path}", output=None)

        content = file_path.read_text(encoding="utf-8")
        return ToolResult(tool=self.name, action="read_file",
                        success=True, output={"content": content, "size": len(content)})

    def _create_file(self, params: dict[str, Any]) -> ToolResult:
        path = params.get("path", "")
        content = params.get("content", "")

        valid, reason = self._sandbox.validate_path(path)
        if not valid:
            return ToolResult(tool=self.name, action="create_file",
                            success=False, error=reason, output=None)

        size_valid, size_reason = self._sandbox.validate_file_size(len(content.encode()))
        if not size_valid:
            return ToolResult(tool=self.name, action="create_file",
                            success=False, error=size_reason, output=None)

        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        return ToolResult(tool=self.name, action="create_file",
                        success=True, output={"path": str(file_path), "size": len(content)})

    def _modify_file(self, params: dict[str, Any]) -> ToolResult:
        path = params.get("path", "")
        content = params.get("content", "")

        valid, reason = self._sandbox.validate_path(path)
        if not valid:
            return ToolResult(tool=self.name, action="modify_file",
                            success=False, error=reason, output=None)

        file_path = Path(path)
        if not file_path.exists():
            return ToolResult(tool=self.name, action="modify_file",
                            success=False, error=f"File not found: {path}", output=None)

        file_path.write_text(content, encoding="utf-8")
        return ToolResult(tool=self.name, action="modify_file",
                        success=True, output={"path": str(file_path), "size": len(content)})

    def _list_files(self, params: dict[str, Any]) -> ToolResult:
        path = params.get("path", str(self.vault_root))
        pattern = params.get("pattern", "*")

        valid, reason = self._sandbox.validate_path(path)
        if not valid:
            return ToolResult(tool=self.name, action="list_files",
                            success=False, error=reason, output=None)

        dir_path = Path(path)
        if not dir_path.is_dir():
            return ToolResult(tool=self.name, action="list_files",
                            success=False, error=f"Not a directory: {path}", output=None)

        files = [str(f.relative_to(dir_path)) for f in dir_path.glob(pattern) if f.is_file()]
        return ToolResult(tool=self.name, action="list_files",
                        success=True, output={"files": files, "count": len(files)})

    def _search_files(self, params: dict[str, Any]) -> ToolResult:
        pattern = params.get("pattern", "*.md")
        path = params.get("path", str(self.vault_root))

        valid, reason = self._sandbox.validate_path(path)
        if not valid:
            return ToolResult(tool=self.name, action="search_files",
                            success=False, error=reason, output=None)

        dir_path = Path(path)
        matches = [str(f) for f in dir_path.rglob(pattern) if f.is_file()]
        return ToolResult(tool=self.name, action="search_files",
                        success=True, output={"matches": matches, "count": len(matches)})

    def _delete_file(self, params: dict[str, Any]) -> ToolResult:
        path = params.get("path", "")

        valid, reason = self._sandbox.validate_path(path)
        if not valid:
            return ToolResult(tool=self.name, action="delete_file",
                            success=False, error=reason, output=None)

        file_path = Path(path)
        if not file_path.exists():
            return ToolResult(tool=self.name, action="delete_file",
                            success=False, error=f"File not found: {path}", output=None)

        file_path.unlink()
        return ToolResult(tool=self.name, action="delete_file",
                        success=True, output={"deleted": str(file_path)})
