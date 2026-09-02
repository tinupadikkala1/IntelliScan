"""Saved Searches dialog — B5-09.

Entry: Tools → Saved Searches, or the "Saved Searches" button inside the
Semantic Search dialog.

Lists persisted semantic searches with Run / Rename / Delete actions.
Re-running always executes against the current FAISS index — saved result
lists are never cached (newly indexed content appears automatically).
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from services.batch5_models import SavedSearchInfo


class SavedSearchesDialog(QDialog):
    """Manage saved semantic searches."""

    run_requested = Signal(object)  # SavedSearchInfo
    saved_changed = Signal()  # a search was created/renamed/deleted

    def __init__(
        self,
        manager,
        on_run: Optional[Callable[[SavedSearchInfo], None]] = None,
        on_changed: Optional[Callable[[], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._on_run = on_run
        self._on_changed = on_changed
        self._items: List[SavedSearchInfo] = []

        self.setWindowTitle("Saved Searches")
        self.setMinimumSize(560, 400)
        self.setModal(False)
        self._setup_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QLabel("⭐ Saved Semantic Searches")
        header.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(header)

        self.search_list = QListWidget()
        self.search_list.setAlternatingRowColors(True)
        self.search_list.itemDoubleClicked.connect(self._on_run_clicked)
        layout.addWidget(self.search_list, 1)

        actions = QHBoxLayout()
        run_btn = QPushButton("Run")
        run_btn.clicked.connect(self._on_run_clicked)
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._on_rename_clicked)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete_clicked)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(run_btn)
        actions.addWidget(rename_btn)
        actions.addWidget(delete_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        try:
            self._items = self._manager.list()
        except Exception as exc:
            QMessageBox.warning(self, "Saved Searches", str(exc))
            self._items = []
        self.search_list.clear()
        for s in self._items:
            scope = s.scope or "workspace"
            label = f"⭐ {s.name}  ·  “{s.query[:48]}”  ·  {scope}"
            if s.last_run:
                label += f"  ·  last run {s.last_run}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, s.id)
            self.search_list.addItem(item)

    def _notify_changed(self) -> None:
        """Fire the on_changed hook (dashboard auto-refresh wiring)."""
        if self._on_changed is not None:
            self._on_changed()

    def _current(self) -> Optional[SavedSearchInfo]:
        item = self.search_list.currentItem()
        if item is None:
            return None
        sid = item.data(Qt.UserRole)
        for s in self._items:
            if s.id == sid:
                return s
        return None

    # ------------------------------------------------------------------ #
    def _on_run_clicked(self) -> None:
        s = self._current()
        if s is None:
            return
        self.run_requested.emit(s)
        if self._on_run is not None:
            self._on_run(s)

    def _on_rename_clicked(self) -> None:
        s = self._current()
        if s is None:
            return
        name, ok = QInputDialog.getText(self, "Rename Search", "New name:", text=s.name)
        if ok and name.strip():
            try:
                self._manager.rename(s.id, name.strip())
                self._notify_changed()
                self.saved_changed.emit()
                self.refresh()
            except Exception as exc:
                QMessageBox.warning(self, "Saved Searches", str(exc))

    def _on_delete_clicked(self) -> None:
        s = self._current()
        if s is None:
            return
        if QMessageBox.question(
            self, "Delete Search", f"Delete saved search '{s.name}'?"
        ) != QMessageBox.Yes:
            return
        self._manager.delete(s.id)
        self._notify_changed()
        self.saved_changed.emit()
        self.refresh()
