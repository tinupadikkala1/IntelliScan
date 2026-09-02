"""Chat dialog — Folder Chat / Workspace Chat entry UI.

Pure presentation. The MainWindow owns conversation persistence and the
chat pipeline; this dialog just renders and forwards signals.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout

from widgets.chat_view import ChatView


class ChatDialog(QDialog):
    """A chat window scoped to a file, folder or the workspace."""

    send_requested = Signal(str)
    stop_requested = Signal()
    citation_activated = Signal(dict)

    def __init__(
        self,
        scope_type: str = "workspace",
        scope_path: str = "",
        title: Optional[str] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._scope_type = scope_type
        self._scope_path = scope_path

        self.setWindowTitle(title or "IntelliVault Chat")
        self.setMinimumSize(680, 560)
        self.setModal(False)

        layout = QVBoxLayout(self)
        scope_label = self._scope_label(scope_type, scope_path)
        self.view = ChatView(scope_label=scope_label)
        layout.addWidget(self.view)

        self.view.send_requested.connect(self.send_requested.emit)
        self.view.stop_requested.connect(self.stop_requested.emit)
        self.view.citation_activated.connect(self.citation_activated.emit)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _scope_label(scope_type: str, scope_path: str) -> str:
        if scope_type == "file":
            return f"📄 File: {scope_path}"
        if scope_type == "folder":
            return f"📁 Folder: {scope_path}"
        return "🌐 Workspace"

    @property
    def scope_type(self) -> str:
        return self._scope_type

    @property
    def scope_path(self) -> str:
        return self._scope_path

    # Presentation proxies ---------------------------------------------- #
    def set_busy_state(self, state: str) -> None:
        self.view.set_state(state)

    def append_user(self, text: str) -> None:
        self.view.add_message("user", text)

    def append_assistant(self, text: str, citations=None) -> None:
        self.view.add_message("assistant", text, citations=citations)

    def append_error(self, text: str) -> None:
        self.view.add_error(text)

    def load_history(self, messages) -> None:
        self.view.load_history(messages)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            return
        super().keyPressEvent(event)

    def clear_messages(self) -> None:
        self.view.clear_messages()

