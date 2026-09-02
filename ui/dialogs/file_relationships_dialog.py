"""File Relationships dialog — B5-07.

Entry: right-click a file → AI → View Relationships, or Tools →
File Relationships.

Lists the FILE → FILE edges (duplicate_of / similar_to / related_to / ...)
touching a selected file, grouped by relationship type, with confidence and
reason. Double-clicking a relationship opens the target file.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from services.batch5_models import FileRelationshipInfo

# Relationship type → emoji glyph (UI only).
_TYPE_ICON = {
    "duplicate_of": "🟰",
    "similar_to": "🔁",
    "related_to": "🔗",
    "references": "📎",
    "derived_from": "⬇️",
    "belongs_to_project": "📁",
}


class FileRelationshipsDialog(QDialog):
    """Shows file-to-file relationships for a source file."""

    file_open_requested = Signal(str)

    def __init__(
        self,
        source_path: str,
        relationships: List[FileRelationshipInfo],
        on_open: Optional[Callable[[str], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._source = source_path
        self._relationships = relationships or []
        self._on_open = on_open

        self.setWindowTitle("File Relationships")
        self.setMinimumSize(680, 460)
        self.setModal(False)
        self._setup_ui()
        self._populate()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        src = QLabel(f"File: {self._source}")
        src.setStyleSheet("font-weight: bold; padding: 4px;")
        src.setWordWrap(True)
        layout.addWidget(src)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; padding: 2px;")
        layout.addWidget(self.status_label)

        self.rel_list = QListWidget()
        self.rel_list.setAlternatingRowColors(True)
        self.rel_list.itemDoubleClicked.connect(self._on_activated)
        layout.addWidget(self.rel_list, 1)

        actions = QHBoxLayout()
        self.open_btn = QPushButton("Open target")
        self.open_btn.clicked.connect(self._on_open_clicked)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(self.open_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self.open_btn.setEnabled(False)

    # ------------------------------------------------------------------ #
    def _populate(self) -> None:
        self.rel_list.clear()
        if not self._relationships:
            self.status_label.setText(
                "No file relationships yet. Use 'Find Similar Files' or "
                "'Find Related Files' to discover connections."
            )
            return

        self.status_label.setText(f"{len(self._relationships)} relationship(s)")
        for rel in self._relationships:
            direction = "→" if rel.source_path == self._source else "←"
            icon = _TYPE_ICON.get(rel.relationship_type, "🔗")
            other = (
                rel.target_path
                if rel.source_path == self._source
                else rel.source_path
            )
            label = (
                f"{icon} {rel.relationship_type} {direction} {os.path.basename(other)}\n"
                f"    {other}\n"
                f"    Confidence: {rel.confidence:.2f}"
                + (f" · {rel.reason}" if rel.reason else "")
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, other)
            self.rel_list.addItem(item)

    # ------------------------------------------------------------------ #
    def _current_target(self) -> Optional[str]:
        item = self.rel_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _on_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.file_open_requested.emit(path)
            if self._on_open is not None:
                self._on_open(path)

    def _on_open_clicked(self) -> None:
        path = self._current_target()
        if path:
            self.file_open_requested.emit(path)
            if self._on_open is not None:
                self._on_open(path)
