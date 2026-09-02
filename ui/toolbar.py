"""Main toolbar.

Provides navigation controls (back/forward/up/refresh), a view switcher
(list/grid), a filename search box, and a semantic (AI) search box.
Each control exposes a signal; the main window routes them to the
appropriate subsystem.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QToolBar, QComboBox, QLineEdit, QWidget


class ToolBar(QToolBar):
    back = Signal()
    forward = Signal()
    up = Signal()
    refresh = Signal()
    view_changed = Signal(str)
    search_submitted = Signal(str)
    scan_requested = Signal()
    ai_index_requested = Signal()
    semantic_search_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__("Main Toolbar", parent)
        self.setMovable(False)

        self._add_action("Back", self.back)
        self._add_action("Forward", self.forward)
        self._add_action("Up", self.up)
        self.addSeparator()
        self._add_action("Refresh", self.refresh)
        self.addSeparator()

        # Scan button (Batch 1)
        self._add_action("Scan Folder", self.scan_requested)
        self._add_action("Index for AI", self.ai_index_requested)
        self.addSeparator()

        self.view_combo = QComboBox()
        self.view_combo.addItems(["List", "Grid"])
        self.view_combo.setCurrentText("List")
        self.view_combo.currentTextChanged.connect(
            lambda t: self.view_changed.emit(t.lower())
        )
        self.addWidget(self.view_combo)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search by filename...")
        self.search_box.returnPressed.connect(
            lambda: self.search_submitted.emit(self.search_box.text())
        )
        self.addWidget(self.search_box)

        # Separator between filename search and semantic search
        self.addSeparator()

        # Semantic (AI) search box (Batch 3)
        self.semantic_search_box = QLineEdit()
        self.semantic_search_box.setPlaceholderText("Semantic search (AI)...")
        self.semantic_search_box.returnPressed.connect(
            lambda: self.semantic_search_requested.emit(
                self.semantic_search_box.text()
            )
        )
        self.addWidget(self.semantic_search_box)

    def _add_action(self, label: str, signal) -> None:
        action = self.addAction(label)
        action.triggered.connect(signal.emit)
