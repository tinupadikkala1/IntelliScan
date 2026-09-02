"""AI Organization Suggestions dialog — B5-08 / B6-05.

Entry: right-click a file → AI → Suggest Organization.

Shows deterministic, evidence-grounded suggestions (target collection or
folder, confidence, reason). Accepting a *collection* suggestion adds the
file to the collection; selecting a *folder* suggestion exposes a
"Move to Folder…" action that opens the approval preview (B6-05) — the
file only moves after explicit user approval.
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
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from services.batch5_models import SuggestionInfo


class SuggestionDialog(QDialog):
    """Show + act on organization suggestions for a file."""

    suggestion_changed = Signal()
    move_requested = Signal(object)  # SuggestionInfo with target_type == 'folder'

    def __init__(
        self,
        engine,
        file_path: str,
        suggestions: List[SuggestionInfo],
        on_accept: Optional[Callable[[int], bool]] = None,
        on_dismiss: Optional[Callable[[int], bool]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._file_path = file_path
        self._suggestions = suggestions or []
        self._on_accept = on_accept
        self._on_dismiss = on_dismiss

        self.setWindowTitle("AI Organization Suggestions")
        self.setMinimumSize(640, 420)
        self.setModal(False)
        self._setup_ui()
        self._populate()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        src = QLabel(f"File: {os.path.basename(self._file_path)}")
        src.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(src)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; padding: 2px;")
        layout.addWidget(self.status_label)

        self.sugg_list = QListWidget()
        self.sugg_list.setAlternatingRowColors(True)
        self.sugg_list.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.sugg_list, 1)

        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("padding: 6px; background: #222; border-radius: 4px;")
        layout.addWidget(self.detail_label)

        actions = QHBoxLayout()
        self.accept_btn = QPushButton("✓ Accept")
        self.accept_btn.clicked.connect(self._on_accept_clicked)
        self.dismiss_btn = QPushButton("✗ Dismiss")
        self.dismiss_btn.clicked.connect(self._on_dismiss_clicked)
        # Batch 6 §10 — approved folder move (only for folder-type targets).
        self.move_btn = QPushButton("📁 Move to Folder…")
        self.move_btn.setToolTip(
            "Preview and approve moving this file into the suggested folder "
            "(requires explicit confirmation — nothing moves automatically)."
        )
        self.move_btn.clicked.connect(self._on_move_clicked)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(self.accept_btn)
        actions.addWidget(self.dismiss_btn)
        actions.addWidget(self.move_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self.accept_btn.setEnabled(False)
        self.dismiss_btn.setEnabled(False)
        self.move_btn.setEnabled(False)
        self.move_btn.setVisible(False)

    # ------------------------------------------------------------------ #
    def _populate(self) -> None:
        self.sugg_list.clear()
        if not self._suggestions:
            self.status_label.setText(
                "No organization suggestions. Create collections first, then "
                "try 'Suggest Organization' again."
            )
            return
        self.status_label.setText(f"{len(self._suggestions)} suggestion(s)")
        for s in self._suggestions:
            icon = "📁" if s.target_type == "folder" else "⭐"
            label = (
                f"{icon} {s.suggested_target}  ·  confidence {s.confidence:.0%}\n"
                f"    {s.reason}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, s.id)
            self.sugg_list.addItem(item)

    def _current(self) -> Optional[SuggestionInfo]:
        item = self.sugg_list.currentItem()
        if item is None:
            return None
        sid = item.data(Qt.UserRole)
        for s in self._suggestions:
            if s.id == sid:
                return s
        return None

    def _on_selection(self) -> None:
        s = self._current()
        if s is None:
            self.detail_label.setText("")
            self.accept_btn.setEnabled(False)
            self.dismiss_btn.setEnabled(False)
            self.move_btn.setEnabled(False)
            self.move_btn.setVisible(False)
            return
        status = s.status if s.status != "pending" else "ready"
        if s.target_type == "folder":
            hint = (
                "Use 'Move to Folder…' to preview and approve moving this file "
                "into the suggested folder. The file moves only after your approval."
            )
        else:
            hint = (
                "Accepting adds this file to the target collection. "
                "It never moves or deletes the file."
            )
        self.detail_label.setText(
            f"Target: {s.suggested_target}  ({s.target_type})\n"
            f"Confidence: {s.confidence:.0%}\n"
            f"Status: {status}\n\n"
            f"Reason: {s.reason or '—'}\n\n"
            + hint
        )
        enabled = s.status == "pending"
        self.accept_btn.setEnabled(enabled)
        self.dismiss_btn.setEnabled(enabled)
        is_folder = s.target_type == "folder" and enabled
        self.move_btn.setEnabled(is_folder)
        self.move_btn.setVisible(s.target_type == "folder")

    def _on_move_clicked(self) -> None:
        s = self._current()
        if s is None or s.target_type != "folder":
            return
        self.move_requested.emit(s)

    # ------------------------------------------------------------------ #
    def _on_accept_clicked(self) -> None:
        s = self._current()
        if s is None:
            return
        ok = self._on_accept(s.id) if self._on_accept else False
        if ok:
            self.status_label.setText(f"Accepted → added to '{s.suggested_target}' ✓")
            self.suggestion_changed.emit()
            self._mark(s.id, "accepted")
        else:
            QMessageBox.information(
                self, "Suggestion",
                "Could not accept: the target collection may no longer exist.",
            )
            self._mark(s.id, "expired")

    def _on_dismiss_clicked(self) -> None:
        s = self._current()
        if s is None:
            return
        if self._on_dismiss:
            self._on_dismiss(s.id)
        self._mark(s.id, "dismissed")

    def _mark(self, sid: int, status: str) -> None:
        for s in self._suggestions:
            if s.id == sid:
                s.status = status
        self._on_selection()
