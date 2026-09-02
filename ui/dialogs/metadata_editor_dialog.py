"""Metadata Editor dialog — B7-6 (#23).

Entry: right-click a file → Edit Metadata (or from the preview panel).

Edits *user-facing* metadata only (title, description, notes, user tags,
custom key/values) — AI-generated values are displayed read-only and are
never overwritten. Save / Cancel with validation.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
)


class MetadataEditorDialog(QDialog):
    """Edits user metadata for one indexed file."""

    def __init__(self, file_path: str, service, parent=None) -> None:
        super().__init__(parent)
        self._file_path = file_path
        self._service = service
        self.setWindowTitle("Edit Metadata")
        self.setMinimumSize(560, 460)
        self._data = service.get(file_path) if service is not None else {}
        self._setup_ui()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        src = QLabel(f"File: {os.path.basename(self._file_path)}")
        src.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(src)

        form = QFormLayout()
        self.title_edit = QLineEdit(self._data.get("title", ""))
        self.desc_edit = QPlainTextEdit(self._data.get("description", ""))
        self.desc_edit.setMaximumHeight(80)
        self.notes_edit = QPlainTextEdit(self._data.get("notes", ""))
        self.notes_edit.setMaximumHeight(80)
        self.tags_edit = QLineEdit(", ".join(self._data.get("user_tags", [])))
        self.custom_edit = QPlainTextEdit(self._custom_to_text())
        self.custom_edit.setMaximumHeight(90)
        form.addRow("Title", self.title_edit)
        form.addRow("Description", self.desc_edit)
        form.addRow("Notes", self.notes_edit)
        form.addRow("User tags (comma-separated)", self.tags_edit)
        form.addRow("Custom (JSON object)", self.custom_edit)
        layout.addLayout(form)

        ai_note = QLabel(
            "AI-generated metadata (category, tags, summary, caption) is "
            "managed separately and is not modified by this dialog."
        )
        ai_note.setWordWrap(True)
        ai_note.setStyleSheet("color: gray; padding: 4px;")
        layout.addWidget(ai_note)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(self.save_btn)
        actions.addStretch(1)
        actions.addWidget(cancel_btn)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #
    def _custom_to_text(self) -> str:
        custom = self._data.get("custom") or {}
        if not custom:
            return "{}"
        import json
        return json.dumps(custom, indent=2, ensure_ascii=False)

    def _custom_from_text(self):
        text = self.custom_edit.toPlainText().strip()
        if not text:
            return {}
        import json
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"Custom metadata is not valid JSON: {exc}") from exc

    # ------------------------------------------------------------------ #
    def _on_save(self) -> None:
        try:
            custom = self._custom_from_text()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            self.status_label.setStyleSheet("color: #c04040;")
            return
        updates = {
            "title": self.title_edit.text(),
            "description": self.desc_edit.toPlainText(),
            "notes": self.notes_edit.toPlainText(),
            "user_tags": self.tags_edit.text(),
            "custom": custom,
        }
        try:
            saved = self._service.save(self._file_path, updates)
            self._data = saved
            self.status_label.setText("✓ Metadata saved")
            self.status_label.setStyleSheet("color: green;")
        except Exception as exc:
            self.status_label.setText(f"Save failed: {exc}")
            self.status_label.setStyleSheet("color: #c04040;")
