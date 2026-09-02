"""Favorites widget.

Lets the user pin frequently-used folders. When a ``repository`` is provided
the list is persisted in the database ``favorites`` table; otherwise it falls
back to config (``favorites.paths``). The widget's public API is identical in
both cases.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
)


class FavoritesWidget(QWidget):
    folder_selected = Signal(str)

    def __init__(self, config, repository=None, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.repository = repository
        self._current_path = ""

        self.list = QListWidget()
        self.add_btn = QPushButton("Add current")
        self.remove_btn = QPushButton("Remove")

        controls = QHBoxLayout()
        controls.addWidget(self.add_btn)
        controls.addWidget(self.remove_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.list)
        layout.addLayout(controls)

        self._load()
        self.list.itemDoubleClicked.connect(self._on_item_activated)
        self.add_btn.clicked.connect(self._add_current)
        self.remove_btn.clicked.connect(self._remove_selected)

    # ------------------------------------------------------------------ #
    def set_current_path(self, path: str) -> None:
        self._current_path = path

    def _paths(self) -> list[str]:
        if self.repository is not None:
            return [f.path for f in self.repository.list_favorites()]
        value = self.config.get("favorites.paths", [])
        return list(value) if isinstance(value, list) else []

    def _load(self) -> None:
        self.list.clear()
        for path in self._paths():
            self._add_item(path)

    def _add_item(self, path: str) -> None:
        item = QListWidgetItem(path)
        item.setData(Qt.UserRole, path)
        self.list.addItem(item)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.folder_selected.emit(path)

    def _add_current(self) -> None:
        path = self._current_path
        if not path or path in self._paths():
            return
        self._add_item(path)
        if self.repository is not None:
            self.repository.add_favorite(path)
        else:
            self.config.set("favorites.paths", self._paths() + [path])

    def _remove_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        path = item.data(Qt.UserRole)
        self.list.takeItem(self.list.row(item))
        if self.repository is not None:
            self.repository.remove_favorite(path)
        else:
            remaining = [p for p in self._paths() if p != path]
            self.config.set("favorites.paths", remaining)
