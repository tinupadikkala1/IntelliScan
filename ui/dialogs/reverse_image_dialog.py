"""Reverse Image Search dialog — B7-1 (#6).

Entry: right-click an image → AI → Search by Image.

Pick a query image, preview it, run image→image CLIP search over the
existing FAISS index, and list visually-similar indexed images with
similarity scores. Double-click opens the result file.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


class ReverseImageDialog(QDialog):
    """Query-by-image similarity search."""

    search_requested = Signal(str)  # query image path

    def __init__(
        self,
        service,
        query_image: str = "",
        open_file: Optional[Callable[[str], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._open_file = open_file
        self._query_image = query_image
        self.setWindowTitle("Reverse Image Search")
        self.setMinimumSize(620, 540)
        self.setModal(False)
        self._setup_ui()
        if query_image:
            self.set_query_image(query_image)

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        picker = QHBoxLayout()
        self.query_edit = QLabel("No query image selected.")
        self.query_edit.setWordWrap(True)
        browse_btn = QPushButton("Choose image…")
        browse_btn.clicked.connect(self._browse)
        picker.addWidget(self.query_edit, 1)
        picker.addWidget(browse_btn)
        layout.addLayout(picker)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(140)
        self.preview_label.setStyleSheet("background: #222; border-radius: 6px; color: #aaa;")
        layout.addWidget(self.preview_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.status_label)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_open)
        layout.addWidget(self.list_widget, 1)

        actions = QHBoxLayout()
        self.search_btn = QPushButton("🔍 Search Similar Images")
        self.search_btn.clicked.connect(self._on_search)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(self.search_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #
    def set_query_image(self, path: str) -> None:
        self._query_image = path
        self.query_edit.setText(f"Query: {path}")
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview_label.setText("(image could not be previewed)")
        else:
            self.preview_label.setPixmap(
                pixmap.scaled(560, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self.search_btn.setEnabled(True)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose query image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif *.gif)",
        )
        if path:
            self.set_query_image(path)

    # ------------------------------------------------------------------ #
    def _on_search(self) -> None:
        if not self._query_image:
            self.status_label.setText("Choose a query image first.")
            self.status_label.setStyleSheet("color: #e0a030; padding: 4px;")
            return
        self.search_btn.setEnabled(False)
        self.status_label.setText("Searching for visually similar images…")
        self.status_label.setStyleSheet("color: gray; padding: 4px;")
        self.list_widget.clear()
        self.search_requested.emit(self._query_image)

    # ------------------------------------------------------------------ #
    def set_results(self, results: list, service_available: bool = True) -> None:
        self.search_btn.setEnabled(True)
        self.list_widget.clear()
        if not service_available:
            self.status_label.setText(
                "CLIP or the AI index is unavailable. Run 'Index for AI' and "
                "ensure the CLIP model is installed."
            )
            self.status_label.setStyleSheet("color: #e0a030; padding: 4px;")
            return
        if not results:
            self.status_label.setText("No visually similar images found.")
            self.status_label.setStyleSheet("color: #e0a030; padding: 4px;")
            return
        self.status_label.setText(f"✓ {len(results)} similar image(s) found")
        self.status_label.setStyleSheet("color: green; padding: 4px;")
        for res in results:
            pct = int(round(res.score * 100))
            item = QListWidgetItem(
                f"📷 Similarity: {pct}%   ·   {os.path.basename(res.file_path)}\n"
                f"    Path: {res.file_path}"
            )
            item.setData(Qt.UserRole, res.file_path)
            item.setData(Qt.UserRole + 1, pct)
            item.setToolTip(res.file_path)
            self.list_widget.addItem(item)

    def set_error(self, message: str) -> None:
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"Search failed: {message}")
        self.status_label.setStyleSheet("color: #c04040; padding: 4px;")

    # ------------------------------------------------------------------ #
    def _on_open(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path and self._open_file is not None:
            self._open_file(path)

