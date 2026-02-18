"""Email plugin — provides email tools via plugin system."""

from plugins.base import PluginBase, PluginManifest
from gold.tools.base import BaseTool
from gold.tools.email import EmailTool


class Plugin(PluginBase):
    """Email plugin for drafting and sending emails."""

    def __init__(self) -> None:
        self._tool = EmailTool()

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="email",
            version="1.0.0",
            description="Email drafting and simulated sending",
        )

    def get_tools(self) -> list[BaseTool]:
        return [self._tool]
