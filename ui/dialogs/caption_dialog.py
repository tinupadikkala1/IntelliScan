"""Image Caption dialog — B6-01 (#7).

Entry: right-click an image → AI → Caption Image.

Shows the image, the generated caption, processing/error state and a
Regenerate action. Presentation-only: caption generation runs in a
background task owned by MainWindow and is delivered via ``set_caption``.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class CaptionDialog(QDialog):
    """Displays an image and its AI caption with regenerate support."""

    regenerate_requested = Signal()

    def __init__(self, file_path: str, parent=None) -> None:
        super().__init__(parent)
        self._file_path = file_path
        self.setWindowTitle("Image Caption")
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

        # Image preview
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(220)
        self.preview_label.setStyleSheet(
            "background: #222; border-radius: 6px; color: #aaa;"
        )
        layout.addWidget(self.preview_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: gray; padding: 4px;")
        layout.addWidget(self.status_label)

        # Caption text area
        self.caption_area = QScrollArea()
        self.caption_area.setWidgetResizable(True)
        self.caption_area.setMaximumHeight(140)
        caption_host = QWidget()
        cap_layout = QVBoxLayout(caption_host)
        cap_layout.setContentsMargins(6, 6, 6, 6)
        self.caption_label = QLabel("No caption yet.")
        self.caption_label.setWordWrap(True)
        self.caption_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cap_layout.addWidget(self.caption_label)
        cap_layout.addStretch(1)
        self.caption_area.setWidget(caption_host)
        layout.addWidget(self.caption_area)

        # Actions
        actions = QHBoxLayout()
        self.regenerate_btn = QPushButton("🔄 Regenerate")
        self.regenerate_btn.clicked.connect(self.regenerate_requested.emit)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(self.regenerate_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    def _load_preview(self) -> None:
        pixmap = QPixmap(self._file_path)
        if pixmap.isNull():
            self.preview_label.setText("(image could not be previewed)")
            return
        self.preview_label.setPixmap(
            pixmap.scaled(
                480, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

    # ------------------------------------------------------------------ #
    def _set_state(self, state: str) -> None:
        self._state = state
        if state == "waiting":
            self.status_label.setText("Generating caption…")
            self.status_label.setStyleSheet("color: gray; padding: 4px;")
            self.regenerate_btn.setEnabled(False)
        elif state == "loading":
            self.status_label.setText("Loading existing caption…")
            self.status_label.setStyleSheet("color: gray; padding: 4px;")
            self.regenerate_btn.setEnabled(True)
        elif state == "ready":
            self.status_label.setText("✓ Caption ready")
            self.status_label.setStyleSheet("color: green; padding: 4px;")
            self.regenerate_btn.setEnabled(True)
        elif state == "error":
            self.status_label.setStyleSheet("color: red; padding: 4px;")
            self.regenerate_btn.setEnabled(True)

    def set_caption(self, caption: str, model: str = "", stale: bool = False) -> None:
        """Deliver the caption text (regenerate path → fresh)."""
        self.caption_label.setText(caption or "(empty caption)")
        note = f"Model: {model}" if model else ""
        if stale:
            note = (note + " · cached") if note else "cached"
        self.status_label.setText(note or "✓ Caption ready")
        self.status_label.setStyleSheet("color: green; padding: 4px;")
        self.regenerate_btn.setEnabled(True)
        self._state = "ready"

    def set_error(self, message: str) -> None:
        self.status_label.setText(f"Error: {message}")
        self.status_label.setStyleSheet("color: red; padding: 4px;")
        self.caption_label.setText("No caption was generated.")
        self.regenerate_btn.setEnabled(True)
        self._state = "error"

    def set_loading(self) -> None:
        self._set_state("loading")
