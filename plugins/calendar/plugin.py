"""Calendar plugin — provides calendar tools via plugin system."""

from plugins.base import PluginBase, PluginManifest
from gold.tools.base import BaseTool
from gold.tools.calendar import CalendarTool


class Plugin(PluginBase):
    """Calendar plugin for scheduling and event management."""

    def __init__(self) -> None:
        self._tool = CalendarTool()

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="calendar",
            version="1.0.0",
            description="Local calendar scheduling and event management",
        )

    def get_tools(self) -> list[BaseTool]:
        return [self._tool]
