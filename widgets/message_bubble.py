"""Message bubble — a single chat message with clickable citations.

Purely presentational: emits ``citation_activated(dict)`` when a citation is
clicked; the owner routes it through the evidence navigator.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_USER_STYLE = (
    "QWidget#bubble { background: palette(alternate-base);"
    " border: 1px solid palette(mid); border-radius: 6px; padding: 6px; }"
)
_AI_STYLE = (
    "QWidget#bubble { background: palette(base);"
    " border: 1px solid palette(highlight); border-radius: 6px; padding: 6px; }"
)


class MessageBubble(QWidget):
    """One chat message with role label, content and citation buttons."""

    citation_activated = Signal(dict)

    def __init__(self, role: str, content: str, citations=None, parent=None) -> None:
        super().__init__(parent)
        self._citations = citations or []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Inner styled container so the frame style does not cascade to
        # the content label and citation buttons.
        inner = QWidget(self)
        inner.setObjectName("bubble")
        inner.setStyleSheet(_USER_STYLE if role == "user" else _AI_STYLE)

        bubble = QVBoxLayout(inner)
        bubble.setContentsMargins(10, 6, 10, 6)
        bubble.setSpacing(4)

        role_label = QLabel("You" if role == "user" else "AI")
        role_label.setStyleSheet("font-weight: bold; color: palette(highlight); background: transparent; border: none;")
        bubble.addWidget(role_label)

        content_label = QLabel(content or "")
        content_label.setWordWrap(True)
        content_label.setStyleSheet("background: transparent; border: none;")
        content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bubble.addWidget(content_label)

        for cit in self._citations:
            citation = cit if isinstance(cit, dict) else getattr(cit, "to_dict", lambda: {})()
            source = citation.get("source_label", "")
            path = citation.get("file_path", "")
            name = os.path.basename(path) if path else "?"
            label = f"📄 {source} — {name}" if source else f"📄 {name}"
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setToolTip(path)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { color: palette(highlight); text-align: left;"
                " background: transparent; border: none; padding: 0; }"
            )
            btn.clicked.connect(lambda _=False, c=citation: self.citation_activated.emit(c))
            bubble.addWidget(btn)

        outer.addWidget(inner)
