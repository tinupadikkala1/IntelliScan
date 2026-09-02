"""Object Detection dialog — B7-2 (#8).

Entry: right-click an image → AI → Detect Objects.

Lists detected objects (label, confidence, optional bounding box) with a
count. Detection runs on demand; results delivered via ``set_objects``.
"""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


class ObjectDetectionDialog(QDialog):
    """Shows detected objects for one image."""

    regenerate_requested = Signal()

    def __init__(self, file_path: str, parent=None) -> None:
        super().__init__(parent)
        self._file_path = file_path
        self.setWindowTitle("Object Detection")
        self.setMinimumSize(560, 520)
        self.setModal(False)
        self._setup_ui()
        self._load_preview()
        self._set_state("waiting")

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        src = QLabel(f"Image: {os.path.basename(self._file_path)}")
        src.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(src)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(180)
        self.preview_label.setStyleSheet("background: #222; border-radius: 6px; color: #aaa;")
        layout.addWidget(self.preview_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.status_label)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        actions = QHBoxLayout()
        self.regenerate_btn = QPushButton("🔄 Re-detect")
        self.regenerate_btn.clicked.connect(self._on_regenerate)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(self.regenerate_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #
    def _load_preview(self) -> None:
        pixmap = QPixmap(self._file_path)
        if pixmap.isNull():
            self.preview_label.setText("(image could not be previewed)")
            return
        self.preview_label.setPixmap(
            pixmap.scaled(480, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    # ------------------------------------------------------------------ #
    def _set_state(self, state: str) -> None:
        if state == "waiting":
            self.status_label.setText("Detecting objects…")
            self.status_label.setStyleSheet("color: gray; padding: 4px;")
            self.regenerate_btn.setEnabled(False)
        elif state == "ready":
            self.regenerate_btn.setEnabled(True)
        elif state == "error":
            self.status_label.setStyleSheet("color: #c04040; padding: 4px;")
            self.regenerate_btn.setEnabled(True)

    def _on_regenerate(self) -> None:
        self._set_state("waiting")
        self.regenerate_requested.emit()

    # ------------------------------------------------------------------ #
    def set_objects(self, objects: List) -> None:
        """Deliver detected objects (list of DetectedObject)."""
        self._set_state("ready")
        self.list_widget.clear()
        if not objects:
            self.status_label.setText("No objects detected (or the vision model is unavailable).")
            self.status_label.setStyleSheet("color: #e0a030; padding: 4px;")
            return
        self.status_label.setText(f"✓ {len(objects)} object(s) detected")
        self.status_label.setStyleSheet("color: green; padding: 4px;")
        for obj in objects:
            box = ""
            if obj.box:
                box = f"  ·  box {obj.box}"
            item = QListWidgetItem(
                f"{obj.label:<20}  confidence {obj.confidence:.2f}{box}"
            )
            self.list_widget.addItem(item)

    def set_error(self, message: str) -> None:
        self._set_state("error")
        self.status_label.setText(f"Error: {message}")
        self.list_widget.clear()
