"""ChatView — reusable conversational UI for Folder/Workspace/Agent chat.

States (Batch 4 §19): ready, retrieving, generating, completed, failed,
cancelled. No fake percentage for LLM generation — a clear busy state is
shown instead. Pure presentation: emits signals, owns no business logic.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from widgets.message_bubble import MessageBubble

_STATE_TEXT = {
    "ready": "",
    "retrieving": "Retrieving evidence…",
    "generating": "Generating answer…",
    "completed": "",
    "failed": "Failed — see error below.",
    "cancelled": "Cancelled.",
}


class ChatView(QWidget):
    """Reusable chat panel."""

    send_requested = Signal(str)
    stop_requested = Signal()
    citation_activated = Signal(dict)

    def __init__(self, scope_label: str = "", parent=None) -> None:
        super().__init__(parent)
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.scope_label = QLabel(scope_label or "🌐 Workspace")
        self.scope_label.setStyleSheet("font-weight: bold; padding: 4px;")
        root.addWidget(self.scope_label)

        # Message area
        self._messages_host = QWidget()
        self._messages_layout = QVBoxLayout(self._messages_host)
        self._messages_layout.setContentsMargins(4, 4, 4, 4)
        self._messages_layout.setSpacing(4)
        self._messages_layout.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self._messages_host)
        root.addWidget(self.scroll, 1)

        # Status line
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; padding: 2px;")
        root.addWidget(self.status_label)

        # Input row
        input_row = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Ask about your files…")
        self.input_box.returnPressed.connect(self._on_send)
        input_row.addWidget(self.input_box, 1)

        self.send_button = QPushButton("Send")
        self.send_button.setAutoDefault(False)
        self.send_button.setDefault(False)
        self.send_button.clicked.connect(self._on_send)
        input_row.addWidget(self.send_button)

        self.stop_button = QPushButton("⏹ Stop")
        self.stop_button.setAutoDefault(False)
        self.stop_button.setDefault(False)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.stop_button.setVisible(False)
        input_row.addWidget(self.stop_button)


        root.addLayout(input_row)

        self.set_state("ready")

    # ------------------------------------------------------------------ #
    def set_scope(self, label: str) -> None:
        self.scope_label.setText(label)

    def set_state(self, state: str) -> None:
        text = _STATE_TEXT.get(state, "")
        self.status_label.setText(text)
        busy = state in ("retrieving", "generating")
        self._busy = busy
        self.stop_button.setVisible(busy)
        self.send_button.setEnabled(not busy)
        self.input_box.setEnabled(not busy)

    @property
    def busy(self) -> bool:
        return self._busy

    def clear_messages(self) -> None:
        while self._messages_layout.count() > 1:  # keep the stretch
            item = self._messages_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def add_message(self, role: str, content: str, citations=None) -> None:
        bubble = MessageBubble(role, content, citations=citations)
        bubble.citation_activated.connect(self.citation_activated.emit)
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, bubble)
        self._scroll_to_bottom()

    def add_error(self, text: str) -> None:
        self.set_state("failed")
        self.add_message("assistant", f"⚠️ {text}")

    def load_history(self, messages) -> None:
        """Populate the view from persisted ChatMessage objects."""
        self.clear_messages()
        for msg in messages:
            citations = getattr(msg, "citations", None) or []
            self.add_message(msg.role, msg.content, citations)

    # ------------------------------------------------------------------ #
    def _on_send(self) -> None:
        text = self.input_box.text().strip()
        if not text or self._busy:
            return
        self.input_box.clear()
        self.send_requested.emit(text)

    def _scroll_to_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
