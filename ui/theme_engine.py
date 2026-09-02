"""Theme engine.

Loads QSS stylesheets from ``resources/themes/`` (with embedded fallbacks) and
applies them to the running ``QApplication``. The current theme is persisted
in config so it survives restarts.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from core.config import Config
from app.signal_bus import SignalBus


class ThemeEngine(QObject):
    theme_changed = Signal(str)

    def __init__(self, config: Config, bus: SignalBus) -> None:
        super().__init__()
        self.config = config
        self.bus = bus
        self._themes_dir = os.path.join(os.path.dirname(__file__), "..", "resources", "themes")

    # ------------------------------------------------------------------ #
    def available(self) -> list[str]:
        return ["dark", "light"]

    def current(self) -> str:
        name = self.config.get("appearance.theme", "dark")
        return name if name in self.available() else "dark"

    def apply(self, name: str | None = None) -> None:
        name = name or self.current()
        if name not in self.available():
            name = "dark"
        qss = self._load(name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)
        self.config.set("appearance.theme", name, save=True)
        self.theme_changed.emit(name)
        self.bus.theme_changed.emit(name)

    def toggle(self) -> str:
        next_theme = "light" if self.current() == "dark" else "dark"
        self.apply(next_theme)
        return next_theme

    # ------------------------------------------------------------------ #
    def _load(self, name: str) -> str:
        path = os.path.join(self._themes_dir, f"{name}.qss")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return fh.read()
            except OSError:
                pass
        return self._fallback(name)

    @staticmethod
    def _fallback(name: str) -> str:
        if name == "light":
            return (
                "QWidget{background-color:#f5f5f5;color:#222222;}"
                "QMenuBar,QStatusBar,QToolBar{background-color:#e7e7e7;}"
                "QListView,QTreeView{background-color:#ffffff;}"
            )
        return (
            "QWidget{background-color:#1e1e1e;color:#eeeeee;}"
            "QMenuBar,QStatusBar,QToolBar{background-color:#2b2b2b;}"
            "QListView,QTreeView{background-color:#252525;}"
            "QPushButton{background-color:#3a3a3a;border:1px solid #555;padding:4px 8px;}"
        )
