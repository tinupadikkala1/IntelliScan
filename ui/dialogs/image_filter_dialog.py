"""AI Image Filtering dialog — B7-10 (#30).

Entry: Tools → AI Image Filter (or right-click an image → AI → Filter by
Image Attributes).

Type a natural-language filter ("images with dogs", "blurry screenshots",
"dark photos with text") and get the matching indexed images, using
existing AI metadata (objects, captions, quality) plus optional CLIP
semantic ranking. Double-click opens a result.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


class ImageFilterDialog(QDialog):
    """Filters indexed images by AI-derived visual attributes."""

    def __init__(
        self,
        service,
        current_folder: str = "",
        open_file: Optional[Callable[[str], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._folder = current_folder
        self._open_file = open_file
        self.setWindowTitle("AI Image Filter")
        self.setMinimumSize(620, 520)
        self.setModal(False)
        self._setup_ui()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        hint = QLabel(
            'Examples: "images with dogs" · "blurry screenshots" · '
            '"photos containing text" · "landscapes"'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; padding: 2px;")
        layout.addWidget(hint)

        row = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Describe the images to keep…")
        self.query_edit.returnPressed.connect(self._on_filter)
        self.filter_btn = QPushButton("Filter")
        self.filter_btn.clicked.connect(self._on_filter)
        row.addWidget(self.query_edit, 1)
        row.addWidget(self.filter_btn)
        layout.addLayout(row)

        self.parsed_label = QLabel("")
        self.parsed_label.setWordWrap(True)
        self.parsed_label.setStyleSheet("padding: 2px;")
        layout.addWidget(self.parsed_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.status_label)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_open)
        layout.addWidget(self.list_widget, 1)

        actions = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #
    def _on_filter(self) -> None:
        query = self.query_edit.text().strip()
        if not query:
            self.status_label.setText("Type a filter query first.")
            self.status_label.setStyleSheet("color: #e0a030; padding: 4px;")
            return

        # Show what the deterministic parser understood.
        try:
            crit = self._service.parse_query(query)
            parts = []
            if crit.objects:
                parts.append("objects: " + ", ".join(crit.objects))
            if crit.quality:
                parts.append("quality: " + crit.quality)
            if crit.require_text:
                parts.append("text required")
            if crit.semantic:
                parts.append("semantic: " + crit.semantic)
            self.parsed_label.setText(
                "Parsed: " + (" · ".join(parts) if parts else "(nothing recognized — "
                "try 'images with X' or 'blurry')")
            )
        except Exception:
            self.parsed_label.setText("")

        self.status_label.setText("Filtering…")
        self.status_label.setStyleSheet("color: gray; padding: 4px;")
        try:
            hits = self._service.filter_images(query, folder=self._folder)
        except Exception as exc:
            self.status_label.setText(f"Filter failed: {exc}")
            self.status_label.setStyleSheet("color: #c04040; padding: 4px;")
            self.list_widget.clear()
            return

        self.list_widget.clear()
        if not hits:
            self.status_label.setText("No images matched the filter.")
            self.status_label.setStyleSheet("color: #e0a030; padding: 4px;")
            return
        self.status_label.setText(f"✓ {len(hits)} image(s) matched")
        self.status_label.setStyleSheet("color: green; padding: 4px;")
        for hit in hits:
            text = os.path.basename(hit.file_path)
            if hit.quality_label:
                text += f"   ·   quality: {hit.quality_label}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, hit.file_path)
            item.setToolTip(f"{hit.file_path}\n{hit.reason}")
            self.list_widget.addItem(item)

    # ------------------------------------------------------------------ #
    def _on_open(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path and self._open_file is not None:
            self._open_file(path)
