"""Metadata Export dialog — B7-3 (#15).

Entry: Tools → Export Metadata.

Scope (workspace / current folder / selected files), format (JSON / CSV),
destination picker, and success/error state. Presentation-only: export runs
synchronously for the small record set and reports through status labels.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QVBoxLayout,
)


class MetadataExportDialog(QDialog):
    """Exports IntelliVault metadata to JSON/CSV."""

    def __init__(
        self,
        service,
        current_folder: str = "",
        selected_files: Optional[List[str]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._current_folder = current_folder
        self._selected_files = selected_files or []
        self.setWindowTitle("Export Metadata")
        self.setMinimumSize(520, 260)
        self.setModal(False)
        self._setup_ui()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["Workspace", "Current folder", "Selected files"])
        if not self._selected_files:
            self.scope_combo.setCurrentIndex(1)
        form.addRow("Scope", self.scope_combo)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["JSON", "CSV"])
        form.addRow("Format", self.format_combo)

        dest_row = QHBoxLayout()
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Choose destination file…")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        dest_row.addWidget(self.dest_edit, 1)
        dest_row.addWidget(browse_btn)
        form.addRow("Destination", dest_row)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.export_btn = QPushButton("Export")
        self.export_btn.clicked.connect(self._on_export)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(self.export_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #
    def _browse(self) -> None:
        fmt = self.format_combo.currentText().lower()
        default = os.path.join(
            self._current_folder or os.path.expanduser("~"),
            f"intellivault_metadata.{fmt}",
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Metadata", default,
            f"{fmt.upper()} files (*.{fmt})",
        )
        if path:
            self.dest_edit.setText(path)

    # ------------------------------------------------------------------ #
    def _on_export(self) -> None:
        dest = self.dest_edit.text().strip()
        if not dest:
            self.status_label.setText("Choose a destination file first.")
            self.status_label.setStyleSheet("color: #e0a030;")
            return
        scope = self.scope_combo.currentText()
        try:
            if scope == "Workspace":
                report = self._service.export(dest, fmt=self.format_combo.currentText().lower())
            elif scope == "Current folder":
                report = self._service.export(
                    dest, fmt=self.format_combo.currentText().lower(),
                    scope="folder", folder=self._current_folder,
                )
            else:
                report = self._service.export(
                    dest, fmt=self.format_combo.currentText().lower(),
                    scope="files", files=self._selected_files,
                )
            from core.file_stat_util import format_file_size
            self.status_label.setText(
                f"✓ Exported {report['count']} files to {report['path']} "
                f"({format_file_size(report['bytes'])}, {report['format'].upper()})"
            )
            self.status_label.setStyleSheet("color: green;")
        except Exception as exc:
            self.status_label.setText(f"Export failed: {exc}")
            self.status_label.setStyleSheet("color: #c04040;")
