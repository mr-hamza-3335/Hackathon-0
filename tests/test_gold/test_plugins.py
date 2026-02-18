"""Tests for Gold tier plugin system."""

import pytest
from gold.tools.base import ToolRegistry
from plugins.base import PluginManager, PluginBase, PluginManifest


class TestPluginManager:
    def test_discover_plugins(self):
        pm = PluginManager()
        discovered = pm.discover_plugins()
        assert "email" in discovered
        assert "filesystem" in discovered
        assert "browser" in discovered
        assert "calendar" in discovered

    def test_load_email_plugin(self):
        registry = ToolRegistry()
        pm = PluginManager(registry=registry)
        assert pm.load_plugin("email") is True
        assert pm.is_loaded("email") is True
        assert registry.get("email") is not None

    def test_load_filesystem_plugin(self):
        registry = ToolRegistry()
        pm = PluginManager(registry=registry)
        assert pm.load_plugin("filesystem") is True
        assert registry.get("filesystem") is not None

    def test_load_browser_plugin(self):
        registry = ToolRegistry()
        pm = PluginManager(registry=registry)
        assert pm.load_plugin("browser") is True
        assert registry.get("browser") is not None

    def test_load_calendar_plugin(self):
        registry = ToolRegistry()
        pm = PluginManager(registry=registry)
        assert pm.load_plugin("calendar") is True
        assert registry.get("calendar") is not None

    def test_load_nonexistent_plugin(self):
        pm = PluginManager()
        assert pm.load_plugin("nonexistent") is False

    def test_unload_plugin(self):
        registry = ToolRegistry()
        pm = PluginManager(registry=registry)
        pm.load_plugin("email")
        assert pm.unload_plugin("email") is True
        assert pm.is_loaded("email") is False
        assert registry.get("email") is None

    def test_load_all(self):
        registry = ToolRegistry()
        pm = PluginManager(registry=registry)
        results = pm.load_all()
        assert all(v is True for v in results.values())

    def test_get_loaded_plugins(self):
        registry = ToolRegistry()
        pm = PluginManager(registry=registry)
        pm.load_plugin("email")
        loaded = pm.get_loaded_plugins()
        assert len(loaded) == 1
        assert loaded[0]["name"] == "email"

    def test_double_load(self):
        registry = ToolRegistry()
        pm = PluginManager(registry=registry)
        assert pm.load_plugin("email") is True
        assert pm.load_plugin("email") is True  # Should not fail
