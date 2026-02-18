"""Plugin base — dynamically loadable plugin architecture.

Plugins are self-contained modules that extend the AI Employee's capabilities.
Each plugin must provide a manifest and implement the PluginBase interface.
"""

import importlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gold.tools.base import BaseTool, ToolRegistry, tool_registry

logger = logging.getLogger("plugins")


@dataclass
class PluginManifest:
    """Describes a plugin's identity and capabilities."""
    name: str
    version: str
    description: str
    author: str = "AI Employee Team"
    tier: str = "gold"  # minimum tier required
    dependencies: list[str] = field(default_factory=list)
    enabled: bool = True


class PluginBase(ABC):
    """Abstract base for all plugins.

    Subclasses must implement:
      - manifest: returns plugin metadata
      - get_tools: returns list of BaseTool instances
      - on_load: called when plugin is loaded
      - on_unload: called when plugin is unloaded
    """

    @property
    @abstractmethod
    def manifest(self) -> PluginManifest:
        """Return the plugin manifest."""
        ...

    @abstractmethod
    def get_tools(self) -> list[BaseTool]:
        """Return the tools provided by this plugin."""
        ...

    def on_load(self) -> None:
        """Called when the plugin is loaded. Override for custom setup."""
        pass

    def on_unload(self) -> None:
        """Called when the plugin is unloaded. Override for custom teardown."""
        pass


class PluginManager:
    """Manages plugin lifecycle: discovery, loading, and unloading."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or tool_registry
        self._plugins: dict[str, PluginBase] = {}
        self._plugins_dir = Path(__file__).parent

    def discover_plugins(self) -> list[str]:
        """Discover available plugins in the plugins/ directory."""
        discovered = []
        for item in self._plugins_dir.iterdir():
            if item.is_dir() and (item / "__init__.py").exists():
                if item.name.startswith("_") or item.name == "__pycache__":
                    continue
                discovered.append(item.name)
        return discovered

    def load_plugin(self, name: str) -> bool:
        """Load a plugin by name.

        Looks for plugins.<name>.plugin module with a Plugin class.
        """
        if name in self._plugins:
            logger.warning(f"Plugin '{name}' is already loaded")
            return True

        try:
            module = importlib.import_module(f"plugins.{name}.plugin")
            plugin_class = getattr(module, "Plugin", None)
            if plugin_class is None:
                logger.error(f"Plugin '{name}' has no Plugin class")
                return False

            plugin = plugin_class()
            if not isinstance(plugin, PluginBase):
                logger.error(f"Plugin '{name}' does not extend PluginBase")
                return False

            manifest = plugin.manifest
            if not manifest.enabled:
                logger.info(f"Plugin '{name}' is disabled")
                return False

            # Call on_load hook
            plugin.on_load()

            # Register tools
            for tool in plugin.get_tools():
                self.registry.register(tool)

            self._plugins[name] = plugin
            logger.info(f"Plugin loaded: {name} v{manifest.version}")
            return True

        except ImportError as e:
            logger.error(f"Failed to import plugin '{name}': {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to load plugin '{name}': {e}")
            return False

    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin."""
        plugin = self._plugins.get(name)
        if not plugin:
            return False

        try:
            # Unregister tools
            for tool in plugin.get_tools():
                self.registry.unregister(tool.name)

            plugin.on_unload()
            del self._plugins[name]
            logger.info(f"Plugin unloaded: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to unload plugin '{name}': {e}")
            return False

    def load_all(self) -> dict[str, bool]:
        """Discover and load all available plugins."""
        results = {}
        for name in self.discover_plugins():
            results[name] = self.load_plugin(name)
        return results

    def get_loaded_plugins(self) -> list[dict[str, Any]]:
        """Get info about all loaded plugins."""
        return [
            {
                "name": p.manifest.name,
                "version": p.manifest.version,
                "description": p.manifest.description,
                "tools": [t.name for t in p.get_tools()],
            }
            for p in self._plugins.values()
        ]

    def is_loaded(self, name: str) -> bool:
        """Check if a plugin is loaded."""
        return name in self._plugins


# Singleton
plugin_manager = PluginManager()
