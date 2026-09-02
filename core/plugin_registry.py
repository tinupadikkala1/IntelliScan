"""Plugin registry and interface.

Defines the contract future AI batches (Batch 1-10) implement so they can
extend IntelliVault without modifying core UI code. A plugin registers with
the :class:`PluginRegistry`, which then fans hook events out to every loaded
plugin. Hook failures are isolated so a bad plugin can never crash the host.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

from PySide6.QtCore import QObject, Signal

from core.logging_setup import get_logger


class PluginInterface(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin name."""

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def subscribed_events(self) -> Iterable[str]:
        """Events this plugin wants to receive. Override to declare subscriptions.
        
        Example:
            @property
            def subscribed_events(self):
                return ["file_opened", "selection_changed"]
        """
        return []

    def register(self, registry: "PluginRegistry") -> None:
        """Called when the plugin is registered. Override to initialise."""

    def unregister(self) -> None:
        """Called when the plugin is removed. Override to clean up."""

    def on_hook(self, event: str, *args: Any) -> None:
        """Called for every hook event the plugin subscribed to."""


class PluginRegistry(QObject):
    plugin_loaded = Signal(str)
    plugin_unloaded = Signal(str)

    def __init__(self, bus=None, parent=None) -> None:
        super().__init__(parent)
        self.bus = bus
        self._plugins: dict[str, PluginInterface] = {}
        self._subscriptions: dict[str, set[str]] = {}  # event -> set of plugin names
        self.log = get_logger("plugins")

    # ------------------------------------------------------------------ #
    def register(self, plugin: PluginInterface) -> None:
        if plugin.name in self._plugins:
            self.log.warning("plugin %s already registered; skipping", plugin.name)
            return
        self._plugins[plugin.name] = plugin
        try:
            plugin.register(self)
        except Exception as exc:  # never let a plugin break startup
            self.log.error("plugin %s failed to register: %s", plugin.name, exc)
            self._plugins.pop(plugin.name, None)
            return
        # Subscribe to declared events (or all if not specified for backward compat)
        events = list(plugin.subscribed_events)
        if not events:
            # Backward compatibility: subscribe to all events if plugin doesn't declare
            events = ["*"]
        for event in events:
            self._subscribe(plugin.name, event)
        self.plugin_loaded.emit(plugin.name)
        if self.bus is not None:
            self.bus.plugin_loaded.emit(plugin.name)
        self.log.info("plugin loaded: %s v%s", plugin.name, plugin.version)

    def unregister(self, name: str) -> None:
        plugin = self._plugins.pop(name, None)
        if plugin is None:
            return
        # Unsubscribe from all events
        for event in list(self._subscriptions.keys()):
            self._unsubscribe(name, event)
        try:
            plugin.unregister()
        except Exception as exc:
            self.log.error("plugin %s failed to unregister: %s", name, exc)
        self.plugin_unloaded.emit(name)
        if self.bus is not None:
            self.bus.plugin_unloaded.emit(name)

    # ------------------------------------------------------------------ #
    def get(self, name: str) -> PluginInterface | None:
        return self._plugins.get(name)

    def all(self) -> list[PluginInterface]:
        return list(self._plugins.values())

    def names(self) -> list[str]:
        return list(self._plugins.keys())

    # ------------------------------------------------------------------ #
    # Subscription management
    # ------------------------------------------------------------------ #
    def _subscribe(self, plugin_name: str, event: str) -> None:
        self._subscriptions.setdefault(event, set()).add(plugin_name)

    def _unsubscribe(self, plugin_name: str, event: str) -> None:
        if event in self._subscriptions:
            self._subscriptions[event].discard(plugin_name)
            if not self._subscriptions[event]:
                self._subscriptions.pop(event, None)

    def subscribe(self, plugin_name: str, events: Iterable[str]) -> None:
        """Manually subscribe a plugin to additional events."""
        for event in events:
            self._subscribe(plugin_name, event)

    def unsubscribe(self, plugin_name: str, events: Iterable[str]) -> None:
        """Manually unsubscribe a plugin from events."""
        for event in events:
            self._unsubscribe(plugin_name, event)

    def subscribed_plugins(self, event: str) -> list[PluginInterface]:
        """Return plugins subscribed to the given event."""
        names = self._subscriptions.get(event, set())
        # Also include plugins subscribed to "*" (all events) for backward compat
        all_event_names = self._subscriptions.get("*", set())
        return [self._plugins[n] for n in (names | all_event_names) if n in self._plugins]

    # ------------------------------------------------------------------ #
    def invoke_hook(self, event: str, *args: Any) -> None:
        """Dispatch hook only to plugins subscribed to this event."""
        for plugin in self.subscribed_plugins(event):
            try:
                plugin.on_hook(event, *args)
            except Exception as exc:
                self.log.error(
                    "hook %r failed in plugin %s: %s", event, plugin.name, exc
                )
