import os

import pytest
from PySide6.QtCore import QElapsedTimer
from PySide6.QtWidgets import QApplication, QLabel

from core.plugin_registry import PluginInterface, PluginRegistry
from core.config import Config
from app.signal_bus import SignalBus
from plugins.loader import load_all
from widgets.preview_panel import PreviewPanel


class DummyPlugin(PluginInterface):
    def __init__(self):
        self.hits = []
        self.registered = False

    @property
    def name(self):
        return "dummy"

    def register(self, registry):
        self.registered = True

    def on_hook(self, event, *args):
        self.hits.append((event, args))


def test_register_and_invoke(qapp):
    reg = PluginRegistry()
    p = DummyPlugin()
    reg.register(p)
    assert p.registered
    reg.invoke_hook("selection_changed", ["/a"])
    assert p.hits == [("selection_changed", (["/a"],))]


def test_unregister_stops_hooks(qapp):
    reg = PluginRegistry()
    p = DummyPlugin()
    reg.register(p)
    reg.unregister("dummy")
    reg.invoke_hook("x")
    assert p.hits == []


def test_plugin_loaded_signal(qapp):
    reg = PluginRegistry()
    loaded = []
    reg.plugin_loaded.connect(loaded.append)
    reg.register(DummyPlugin())
    assert "dummy" in loaded


def test_hook_failure_is_isolated(qapp):
    class BadPlugin(PluginInterface):
        @property
        def name(self):
            return "bad"

        def on_hook(self, event, *args):
            raise RuntimeError("boom")

    reg = PluginRegistry()
    reg.register(BadPlugin())
    good = DummyPlugin()
    reg.register(good)
    # Bad plugin must not break the dispatch to the good one.
    reg.invoke_hook("e")
    assert good.hits == [("e", ())]


def test_loader_discovers_example_plugin(qapp):
    reg = PluginRegistry()
    loaded = load_all(reg)
    assert "example" in reg.names()
    assert "example" in loaded


def test_example_plugin_fills_ai_insights(qapp, tmp_path):
    reg = PluginRegistry()
    load_all(reg)
    # Create a small file and show it in a preview wired to the registry.
    f = str(tmp_path / "note.txt")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("hi")
    panel = PreviewPanel(SignalBus(), plugin_registry=reg)
    panel.show_file(f)
    # The example plugin should have enabled the reserved AI group and
    # rewritten its first label without the core UI being modified.
    assert panel.ai_group.isEnabled()
    first = panel.ai_group.findChildren(QLabel)[0]
    assert "ExamplePlugin" in first.text()


def test_container_loads_plugins(qapp):
    from app.container import Container

    c = Container()
    assert "example" in c.plugins.names()
    c.shutdown()
