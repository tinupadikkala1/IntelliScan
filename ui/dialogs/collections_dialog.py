"""Collections dialog — B5-03.

Entry: Tools → Collections.

Virtual collections (files are never moved/copied):
- Static collections: explicit members added from the dialog or via the
  file context menu.
- Smart collections: membership derived from criteria (category / tag /
  extension / folder / semantic query) and refreshed on demand.

Layout: left = collection list, right = members + criteria editor.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.batch5_models import CollectionInfo


class CollectionsDialog(QDialog):
    """Manage virtual collections (create/edit/delete, members, criteria)."""

    file_open_requested = Signal(str)
    add_files_requested = Signal(int)  # collection_id

    def __init__(
        self,
        engine,
        on_open: Optional[Callable[[str], None]] = None,
        on_add_files: Optional[Callable[[int], None]] = None,
        on_changed: Optional[Callable[[], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._on_open = on_open
        self._on_add_files = on_add_files
        self._on_changed = on_changed
        self._collections: List[CollectionInfo] = []

        self.setWindowTitle("Collections")
        self.setMinimumSize(820, 560)
        self.setModal(False)
        self._setup_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        # Left: collection list + CRUD
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Collections:"))
        self.collection_list = QListWidget()
        self.collection_list.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.collection_list, 1)

        left_actions = QHBoxLayout()
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self._on_new)
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._on_rename)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)
        left_actions.addWidget(new_btn)
        left_actions.addWidget(rename_btn)
        left_actions.addWidget(delete_btn)
        left_layout.addLayout(left_actions)
        splitter.addWidget(left)

        # Right: details
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.detail_title = QLabel("")
        self.detail_title.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(self.detail_title)

        # Criteria editor (smart)
        crit_group = QWidget()
        crit_layout = QFormLayout(crit_group)
        self.crit_category = QComboBox()
        self.crit_category.addItem("(any)")
        for cat in ("document", "code", "image", "audio", "video", "presentation",
                    "spreadsheet", "research", "education", "project", "business",
                    "personal", "archive", "other"):
            self.crit_category.addItem(cat)
        self.crit_tag = QLineEdit()
        self.crit_tag.setPlaceholderText("canonical tag, e.g. machine-learning")
        self.crit_ext = QLineEdit()
        self.crit_ext.setPlaceholderText("e.g. .pdf")
        self.crit_folder = QLineEdit()
        self.crit_folder.setPlaceholderText("absolute folder path")
        self.crit_semantic = QLineEdit()
        self.crit_semantic.setPlaceholderText("natural-language query (optional)")
        self.is_smart_check = QCheckBox("Smart collection (derive membership from criteria)")
        crit_layout.addRow(self.is_smart_check)
        crit_layout.addRow("Category", self.crit_category)
        crit_layout.addRow("Tag", self.crit_tag)
        crit_layout.addRow("Extension", self.crit_ext)
        crit_layout.addRow("Folder", self.crit_folder)
        crit_layout.addRow("Semantic query", self.crit_semantic)
        right_layout.addWidget(crit_group)

        crit_actions = QHBoxLayout()
        apply_crit_btn = QPushButton("Apply criteria")
        apply_crit_btn.clicked.connect(self._on_apply_criteria)
        refresh_btn = QPushButton("Refresh membership")
        refresh_btn.clicked.connect(self._on_refresh_membership)
        crit_actions.addWidget(apply_crit_btn)
        crit_actions.addWidget(refresh_btn)
        right_layout.addLayout(crit_actions)

        # Members
        right_layout.addWidget(QLabel("Members:"))
        self.members_list = QListWidget()
        self.members_list.setAlternatingRowColors(True)
        self.members_list.itemDoubleClicked.connect(self._on_member_activated)
        right_layout.addWidget(self.members_list, 1)

        member_actions = QHBoxLayout()
        add_files_btn = QPushButton("Add files...")
        add_files_btn.clicked.connect(self._on_add_files_clicked)
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._on_remove_member)
        member_actions.addWidget(add_files_btn)
        member_actions.addWidget(remove_btn)
        member_actions.addStretch(1)
        right_layout.addLayout(member_actions)

        splitter.addWidget(right)
        splitter.setSizes([300, 520])
        layout.addWidget(splitter)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        self._collections = self._engine.list()
        self.collection_list.clear()
        for c in self._collections:
            kind = "⭐" if c.is_smart else "📁"
            label = f"{kind} {c.name} ({c.member_count})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, c.id)
            self.collection_list.addItem(item)
        self._load_detail(None)

    def _current_collection(self) -> Optional[CollectionInfo]:
        item = self.collection_list.currentItem()
        if item is None:
            return None
        cid = item.data(Qt.UserRole)
        for c in self._collections:
            if c.id == cid:
                return c
        return None

    # ------------------------------------------------------------------ #
    def _load_detail(self, collection: Optional[CollectionInfo]) -> None:
        if collection is None:
            self.detail_title.setText("No collection selected")
            self.members_list.clear()
            self.is_smart_check.setChecked(False)
            self.crit_category.setCurrentIndex(0)
            self.crit_tag.clear()
            self.crit_ext.clear()
            self.crit_folder.clear()
            self.crit_semantic.clear()
            return

        self.detail_title.setText(
            f"{'⭐' if collection.is_smart else '📁'} {collection.name} "
            f"· {collection.member_count} member(s)"
        )
        self.is_smart_check.setChecked(collection.is_smart)
        criteria = collection.criteria or {}
        self.crit_category.setCurrentText(criteria.get("category", "(any)"))
        self.crit_tag.setText(criteria.get("tag", ""))
        self.crit_ext.setText(criteria.get("extension", ""))
        self.crit_folder.setText(criteria.get("folder", ""))
        self.crit_semantic.setText(criteria.get("semantic_query", ""))

        self.members_list.clear()
        try:
            for path in self._engine.member_paths(collection.id):
                item = QListWidgetItem(path)
                item.setData(Qt.UserRole, path)
                self.members_list.addItem(item)
        except Exception as exc:
            QMessageBox.warning(self, "Collections", f"Could not load members: {exc}")

    def _on_selection_changed(self) -> None:
        self._load_detail(self._current_collection())

    # ------------------------------------------------------------------ #
    def _on_new(self) -> None:
        name, ok = self._prompt_name("New Collection", "Collection name:")
        if not ok or not name:
            return
        try:
            cid = self._engine.create(name)
            self._notify_changed()
            self.refresh()
            for i in range(self.collection_list.count()):
                if self.collection_list.item(i).data(Qt.UserRole) == cid:
                    self.collection_list.setCurrentRow(i)
                    break
        except Exception as exc:
            QMessageBox.warning(self, "Collections", str(exc))

    def _on_rename(self) -> None:
        c = self._current_collection()
        if c is None:
            return
        name, ok = self._prompt_name("Rename Collection", "New name:", c.name)
        if ok and name:
            self._engine.rename(c.id, name)
            self._notify_changed()
            self.refresh()

    def _on_delete(self) -> None:
        c = self._current_collection()
        if c is None:
            return
        if QMessageBox.question(self, "Delete Collection",
                                f"Delete collection '{c.name}'?") != QMessageBox.Yes:
            return
        self._engine.delete(c.id)
        self._notify_changed()
        self.refresh()

    def _on_apply_criteria(self) -> None:
        c = self._current_collection()
        if c is None:
            QMessageBox.information(self, "Collections", "Select a collection first.")
            return
        criteria = {}
        if self.crit_category.currentText() != "(any)":
            criteria["category"] = self.crit_category.currentText()
        if self.crit_tag.text().strip():
            criteria["tag"] = self.crit_tag.text().strip()
        if self.crit_ext.text().strip():
            criteria["extension"] = self.crit_ext.text().strip()
        if self.crit_folder.text().strip():
            criteria["folder"] = self.crit_folder.text().strip()
        if self.crit_semantic.text().strip():
            criteria["semantic_query"] = self.crit_semantic.text().strip()
        self._engine.update_criteria(c.id, criteria)
        self._notify_changed()
        self.refresh()

    def _on_refresh_membership(self) -> None:
        c = self._current_collection()
        if c is None:
            return
        try:
            count = self._engine.refresh(c.id)
            self.bus_status(f"Refreshed: {count} member(s)")
            self._notify_changed()
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Collections", f"Refresh failed: {exc}")

    def bus_status(self, message: str) -> None:
        # Overridden by MainWindow wiring if desired; default no-op.
        pass

    # ------------------------------------------------------------------ #
    def _on_add_files_clicked(self) -> None:
        c = self._current_collection()
        if c is None:
            QMessageBox.information(self, "Collections", "Select a collection first.")
            return
        if c.is_smart:
            QMessageBox.information(
                self, "Collections",
                "Smart collections derive membership from criteria. "
                "Use 'Refresh membership' to update, or add files manually anyway.",
            )
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files to collection")
        for path in paths:
            self._engine.add_member(c.id, path)
        if paths:
            self._notify_changed()
        self.refresh()

    def _on_remove_member(self) -> None:
        c = self._current_collection()
        item = self.members_list.currentItem()
        if c is None or item is None:
            return
        path = item.data(Qt.UserRole)
        self._engine.remove_member(c.id, path)
        self._notify_changed()
        self.refresh()

    def _on_member_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.file_open_requested.emit(path)
            if self._on_open is not None:
                self._on_open(path)

    def _notify_changed(self) -> None:
        """Fire the on_changed hook (dashboard auto-refresh wiring)."""
        if self._on_changed is not None:
            self._on_changed()

    # ------------------------------------------------------------------ #
    def _prompt_name(self, title: str, label: str, initial: str = ""):
        from PySide6.QtWidgets import QInputDialog
        return QInputDialog.getText(self, title, label, text=initial)
