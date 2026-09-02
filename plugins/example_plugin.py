"""Example plugin (demonstration only).

Shows how a future AI batch plugs into IntelliVault without changing core
code: it reacts to hook events and populates the reserved "AI Insights"
area of the preview panel. This plugin ships only to prove the extension
points work; real AI batches (OCR, embeddings, LLM, ...) replace it.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from core.logging_setup import get_logger
from core.plugin_registry import PluginInterface


class ExamplePlugin(PluginInterface):
    @property
    def name(self) -> str:
        return "example"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def subscribed_events(self):
        return ["file_opened", "preview_render"]

    def register(self, registry) -> None:
        self._log = get_logger("plugins.example")

    def on_hook(self, event: str, *args) -> None:
        if event == "file_opened":
            path = args[0] if args else ""
            self._log.info("ExamplePlugin: file opened -> %s", path)
        elif event == "preview_render":
            # args: (path, preview_panel)
            if len(args) < 2:
                return
            panel = args[1]
            try:
                panel.ai_group.setEnabled(True)
                labels = panel.ai_group.findChildren(QLabel)
                if labels:
                    labels[0].setEnabled(True)
                    labels[0].setText("• Summary (provided by ExamplePlugin)")
            except Exception:
                pass


def setup(registry) -> None:
    registry.register(ExamplePlugin())
