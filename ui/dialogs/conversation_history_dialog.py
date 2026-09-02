"""Conversation history dialog (Batch 4 §44).

Lists saved conversations (title, scope, message count, updated time) and
lets the user resume or delete one. Pure presentation: MainWindow performs
the actual resume via signals.
"""

from __future__ import annotations

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


class ConversationHistoryDialog(QDialog):
    """Shows past conversations; emits signals for resume/delete."""

    resume_requested = Signal(int)          # conversation_id
    delete_requested = Signal(int)          # conversation_id
    new_requested = Signal()

    def __init__(self, conversations: List[dict], parent=None,
                 on_resume: Optional[Callable[[int], None]] = None,
                 on_delete: Optional[Callable[[int], None]] = None) -> None:
        super().__init__(parent)
        self._conversations = conversations
        self._on_resume = on_resume
        self._on_delete = on_delete

        self.setWindowTitle("Conversation History")
        self.setMinimumSize(560, 420)
        self.setModal(False)

        layout = QVBoxLayout(self)
        header = QLabel("Saved conversations — double-click to resume")
        header.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(header)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemDoubleClicked.connect(self._on_resume_item)
        layout.addWidget(self.list_widget, 1)

        buttons = QHBoxLayout()
        self.resume_btn = QPushButton("Resume")
        self.resume_btn.clicked.connect(self._on_resume_clicked)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.resume_btn)
        buttons.addWidget(self.delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        self._populate()

    # ------------------------------------------------------------------ #
    def _populate(self) -> None:
        self.list_widget.clear()
        for c in self._conversations:
            scope = c.get("scope_type", "workspace")
            icon = {"file": "📄", "folder": "📁", "workspace": "🌐"}.get(scope, "💬")
            title = c.get("title") or "Untitled"
            count = c.get("message_count", 0)
            updated = c.get("updated_at", "") or ""
            label = f"{icon} {title}  ·  {count} messages  ·  {updated}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, c.get("id"))
            self.list_widget.addItem(item)

    # ------------------------------------------------------------------ #
    def _selected_id(self) -> Optional[int]:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _on_resume_item(self, item: QListWidgetItem) -> None:
        cid = item.data(Qt.UserRole)
        if cid is not None:
            self.resume_requested.emit(cid)
            if self._on_resume:
                self._on_resume(cid)

    def _on_resume_clicked(self) -> None:
        cid = self._selected_id()
        if cid is not None:
            self.resume_requested.emit(cid)
            if self._on_resume:
                self._on_resume(cid)

    def _on_delete_clicked(self) -> None:
        cid = self._selected_id()
        if cid is not None:
            self.delete_requested.emit(cid)
            if self._on_delete:
                self._on_delete(cid)
            self._populate()
