"""Drives / volumes widget.

Lists the root filesystem plus common mount points so the user can jump
straight to a volume. Linux-only (Ubuntu target); scans ``/``, ``~``,
``/mnt`` and ``/media``.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QListWidget, QListWidgetItem, QVBoxLayout


class DrivesWidget(QWidget):
    folder_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.list = QListWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.list)
        self._populate()
        self.list.itemDoubleClicked.connect(self._on_activated)

    def _populate(self) -> None:
        candidates = ["/", os.path.expanduser("~")]
        for base in ("/mnt", "/media"):
            if os.path.isdir(base):
                for name in sorted(os.listdir(base)):
                    full = os.path.join(base, name)
                    if os.path.isdir(full):
                        candidates.append(full)
        for path in candidates:
            item = QListWidgetItem(path)
            item.setData(Qt.UserRole, path)
            self.list.addItem(item)

    def _on_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.folder_selected.emit(path)
