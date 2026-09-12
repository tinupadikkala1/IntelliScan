"""Dock manager.

Owns the dockable Navigation (left) and Preview (right) panels so they can be
shown/hidden and later populated by M3 (navigation) and M5 (preview) without
the main window knowing their internals.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QLabel, QWidget

from ui.indexed_files_widget import IndexedFilesWidget


class DockManager:
    # Fixed layout constants — file list vs preview spacing is locked.
    # Central explorer takes remaining width; user cannot drag/resize docks.
    SIDEBAR_WIDTH = 250
    PREVIEW_WIDTH = 350

    def __init__(self, window) -> None:
        self.window = window

        self.sidebar_dock = QDockWidget("Navigation", window)
        self.sidebar_dock.setAllowedAreas(Qt.LeftDockWidgetArea)
        self.sidebar_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.sidebar_dock.setFloating(False)
        self.sidebar_dock.setWidget(QLabel("Navigation panel\\n(M3)", self.sidebar_dock))
        self.sidebar_dock.setFixedWidth(self.SIDEBAR_WIDTH)
        self.sidebar_dock.setMinimumWidth(self.SIDEBAR_WIDTH)
        self.sidebar_dock.setMaximumWidth(self.SIDEBAR_WIDTH)

        self.preview_dock = QDockWidget("Preview", window)
        self.preview_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.preview_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.preview_dock.setFloating(False)
        self.preview_dock.setWidget(QLabel("Preview panel\\n(M5)", self.preview_dock))
        self.preview_dock.setFixedWidth(self.PREVIEW_WIDTH)
        self.preview_dock.setMinimumWidth(self.PREVIEW_WIDTH)
        self.preview_dock.setMaximumWidth(self.PREVIEW_WIDTH)

        window.setDockNestingEnabled(False)
        window.addDockWidget(Qt.LeftDockWidgetArea, self.sidebar_dock)
        window.addDockWidget(Qt.RightDockWidgetArea, self.preview_dock)

    # ------------------------------------------------------------------ #
    def set_sidebar_widget(self, widget: QWidget) -> None:
        self.sidebar_dock.setWidget(widget)

    def set_preview_widget(self, widget: QWidget) -> None:
        self.preview_dock.setWidget(widget)

    def add_indexed_files_widget(self, container) -> None:
        """Create indexed files widget (embedded in central layout, not a dock)."""
        self.indexed_files_widget = IndexedFilesWidget(container)

    def toggle_sidebar(self) -> None:
        self.sidebar_dock.setVisible(not self.sidebar_dock.isVisible())

    def toggle_preview(self) -> None:
        self.preview_dock.setVisible(not self.preview_dock.isVisible())

    def show_sidebar(self, visible: bool) -> None:
        self.sidebar_dock.setVisible(visible)

    def show_preview(self, visible: bool) -> None:
        self.preview_dock.setVisible(visible)
