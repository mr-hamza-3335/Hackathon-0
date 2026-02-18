"""Filesystem plugin — provides file operation tools via plugin system."""

from plugins.base import PluginBase, PluginManifest
from gold.tools.base import BaseTool
from gold.tools.filesystem import FilesystemTool


class Plugin(PluginBase):
    """Filesystem plugin for safe file operations."""

    def __init__(self) -> None:
        self._tool = FilesystemTool()

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="filesystem",
            version="1.0.0",
            description="Safe file operations within the vault",
        )

    def get_tools(self) -> list[BaseTool]:
        return [self._tool]
