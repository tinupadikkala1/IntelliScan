"""Breadcrumb navigation.

Renders the current path as clickable segments and provides an editable path
field. Either interaction emits ``path_changed``.
"""

from __future__ import annotations

import os
from pathlib import PurePosixPath

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QScrollArea,
)


class Breadcrumb(QWidget):
    path_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Path")
        self.edit.returnPressed.connect(self._submit)

        self.container = QWidget()
        self.hbox = QHBoxLayout(self.container)
        self.hbox.setContentsMargins(0, 0, 0, 0)
        self.hbox.setSpacing(2)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.container)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.edit)

    # ------------------------------------------------------------------ #
    def set_path(self, path: str) -> None:
        self.edit.setText(path)
        self._render(path)

    def _render(self, path: str) -> None:
        while self.hbox.count():
            widget = self.hbox.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()

        parts = [p for p in PurePosixPath(path).parts]
        if not parts:
            parts = ["/"]

        accumulated = ""
        for part in parts:
            accumulated = os.path.join(accumulated, part) if accumulated else part
            btn = QPushButton(part)
            btn.setMaximumWidth(160)
            btn.clicked.connect(lambda _checked=False, p=accumulated: self.path_changed.emit(p))
            self.hbox.addWidget(btn)
            sep = QLabel("›")
            self.hbox.addWidget(sep)
        self.hbox.addStretch(1)

    def _submit(self) -> None:
        self.path_changed.emit(self.edit.text())
