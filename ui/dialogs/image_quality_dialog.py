"""Image Quality Analysis dialog — B7-4 (#20).

Entry: right-click an image → AI → Analyze Image Quality.

Displays the deterministic quality score, label, resolution, sharpness,
exposure, contrast and the metric breakdown. Analysis runs on demand; the
result is delivered via ``set_result``.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class ImageQualityDialog(QDialog):
    """Shows image-quality metrics for one image."""

    def __init__(self, file_path: str, parent=None) -> None:
        super().__init__(parent)
        self._file_path = file_path
        self.setWindowTitle("Image Quality Analysis")
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

        self.metrics_label = QLabel("")
        self.metrics_label.setWordWrap(True)
        self.metrics_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.metrics_label.setStyleSheet("padding: 8px; background: #222; border-radius: 6px;")
        layout.addWidget(self.metrics_label, 1)

        actions = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #
    def _load_preview(self) -> None:
        pixmap = QPixmap(self._file_path)
        if pixmap.isNull():
            self.preview_label.setText("(image could not be previewed)")
            return
        self.preview_label.setPixmap(pixmap.scaled(480, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # ------------------------------------------------------------------ #
    def _set_state(self, state: str) -> None:
        if state == "waiting":
            self.status_label.setText("Analyzing image quality…")
            self.status_label.setStyleSheet("color: gray; padding: 4px;")
        elif state == "error":
            self.status_label.setStyleSheet("color: #c04040; padding: 4px;")

    def set_result(self, result) -> None:
        """Deliver a QualityResult (or None for failure)."""
        if result is None:
            self.status_label.setText("Quality analysis failed — the image could not be read.")
            self.status_label.setStyleSheet("color: #c04040; padding: 4px;")
            self.metrics_label.setText("")
            return
        color = {"Good": "green", "Fair": "#e0a030", "Poor": "#c07030",
                 "Very Poor": "#c04040"}.get(result.label, "gray")
        self.status_label.setText(
            f"Score: {result.score:.2f} / 1.00   ·   Label: <b style='color:{color}'>{result.label}</b>"
        )
        self.status_label.setStyleSheet("padding: 4px;")
        from core.file_stat_util import format_file_size

        lines = [
            f"Resolution: {result.width} × {result.height} px  (aspect {result.aspect_ratio:.2f})",
            f"File size: {format_file_size(result.file_size, include_exact=True)}",
            f"Sharpness: {result.sharpness:.3f}",
            f"Contrast: {result.contrast:.3f}",
            f"Brightness / exposure: {result.brightness:.3f}",
            f"Noise estimate: {result.noise:.3f}",
        ]
        if result.metrics:
            lines.append("")
            lines.append("Factor scores: " + "  ·  ".join(
                f"{k}: {v:.2f}" for k, v in result.metrics.items()
            ))
        self.metrics_label.setText("\n".join(lines))

    def set_error(self, message: str) -> None:
        self.status_label.setText(f"Error: {message}")
        self.status_label.setStyleSheet("color: #c04040; padding: 4px;")
        self.metrics_label.setText("")
