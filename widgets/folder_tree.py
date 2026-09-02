"""Folder tree navigation widget.

A recursive directory tree backed by :class:`QFileSystemModel`. Selecting a
folder emits ``folder_selected`` which the main window routes to the signal
bus as ``path_changed``.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QDir, QModelIndex, Signal
from PySide6.QtWidgets import QTreeView, QFileSystemModel


class FolderTree(QTreeView):
    folder_selected = Signal(str)

    def __init__(self, model: QFileSystemModel | None = None, parent=None) -> None:
        super().__init__(parent)
        if model is None:
            model = QFileSystemModel()
            model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot)
            model.setRootPath("")
        self._model = model
        self.setModel(self._model)
        self.setColumnHidden(1, True)
        self.setColumnHidden(2, True)
        self.setColumnHidden(3, True)
        self.clicked.connect(self._on_clicked)
        self.setHeaderHidden(True)
        # Start expanded at the user's home directory.
        home = os.path.expanduser("~")
        self.setRootIndex(self._model.index(home))
        self.expand(self._model.index(home))

    # ------------------------------------------------------------------ #
    def _on_clicked(self, index: QModelIndex) -> None:
        path = self._model.filePath(index)
        if self._model.isDir(index):
            self.folder_selected.emit(path)

    def navigate_to(self, path: str) -> None:
        index = self._model.index(path)
        if index.isValid():
            self.setCurrentIndex(index)
            self.scrollTo(index)
            self.expand(index)
