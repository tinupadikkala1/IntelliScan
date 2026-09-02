"""Agent Mode dialog (Batch 4 M11, §38-§39).

Displays concise action status lines ("✓ Searched workspace", "✓ Found 4
relevant documents"), a Stop button, and the final synthesized answer with
citations. No hidden chain-of-thought is shown. Pure presentation: all
work is driven by MainWindow via signals.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from widgets.chat_view import ChatView


class AgentDialog(QDialog):
    """Agent Mode dialog."""

    send_requested = Signal(str)
    stop_requested = Signal()
    citation_activated = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Agent Mode")
        self.setMinimumSize(720, 600)
        self.setModal(False)

        layout = QVBoxLayout(self)

        header = QLabel("🤖 Agent Mode — bounded read-only research over your files")
        header.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(header)

        self.view = ChatView(scope_label="🧭 Agent actions")
        layout.addWidget(self.view, 1)

        # Action status strip (concise, user-relevant actions only)
        status_row = QHBoxLayout()
        self.action_label = QLabel("Ready.")
        self.action_label.setStyleSheet("color: #495057; padding: 2px;")
        status_row.addWidget(self.action_label, 1)
        self.status_badge = QLabel("")
        self.status_badge.setStyleSheet("color: gray; padding: 2px;")
        status_row.addWidget(self.status_badge)
        layout.addLayout(status_row)

        self.view.send_requested.connect(self.send_requested.emit)
        self.view.stop_requested.connect(self._on_stop)
        self.view.citation_activated.connect(self.citation_activated.emit)

    # ------------------------------------------------------------------ #
    def _on_stop(self) -> None:
        self.stop_requested.emit()
        self.set_action("Stopping…")

    def set_action(self, text: str) -> None:
        """Show a concise action status line."""
        self.action_label.setText(text)

    def add_action_line(self, text: str) -> None:
        """Append a completed-action line (e.g. '✓ Searched workspace')."""
        self.action_label.setText(text)

    def set_state(self, state: str) -> None:
        self.view.set_state(state)
        if state == "ready":
            self.status_badge.setText("")
        elif state == "cancelled":
            self.status_badge.setText("cancelled")
        elif state == "failed":
            self.status_badge.setText("failed")
        elif state in ("retrieving", "generating"):
            self.status_badge.setText("working…")

    def append_user(self, text: str) -> None:
        self.view.add_message("user", text)

    def append_assistant(self, text: str, citations=None) -> None:
        self.view.add_message("assistant", text, citations=citations)

    def append_error(self, text: str) -> None:
        self.view.add_error(text)

    def append_info(self, text: str) -> None:
        self.view.add_message("assistant", text)
