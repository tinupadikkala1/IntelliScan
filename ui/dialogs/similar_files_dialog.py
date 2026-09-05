"""Similar / Related Files dialog — B5-05 & B5-06.

Entry: right-click a file → AI → Find Similar Files (near duplicates) or
Find Related Files (combined similarity + graph + semantic discovery).

Clearly distinguishes near duplicates from related files; each result is
clickable and opens the target through the existing preview/open path.
"""

from __future__ import annotations

import os
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

from services.batch5_models import RelatedFileResult, SimilarFileResult


class SimilarFilesDialog(QDialog):
    """Shows near-duplicate / related files for a selected file."""

    file_open_requested = Signal(str)
    show_in_folder_requested = Signal(str)
    compare_requested = Signal(str, str)  # (file_a, file_b)
    trash_requested = Signal(str)  # file_path to trash

    def __init__(
        self,
        source_path: str,
        similar: List[SimilarFileResult],
        related: List[RelatedFileResult] | None = None,
        on_open: Optional[Callable[[str], None]] = None,
        on_compare: Optional[Callable[[str, str], None]] = None,
        on_trash: Optional[Callable[[str], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._source = source_path
        self._similar = similar or []
        self._related = related or []
        self._on_open = on_open
        self._on_compare = on_compare
        self._on_trash = on_trash

        self.setWindowTitle("Similar & Related Files")
        self.setMinimumSize(780, 560)
        self.setModal(False)
        self._setup_ui()
        self._populate()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        src = QLabel(f"Source: {self._source}")
        src.setStyleSheet("font-weight: bold; padding: 4px;")
        src.setWordWrap(True)
        layout.addWidget(src)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; padding: 2px;")
        layout.addWidget(self.status_label)

        self.results_list = QListWidget()
        self.results_list.setAlternatingRowColors(True)
        self.results_list.itemDoubleClicked.connect(self._on_activated)
        self.results_list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.results_list, 1)

        actions = QHBoxLayout()
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(self._on_open_clicked)
        self.folder_btn = QPushButton("Show in folder")
        self.folder_btn.clicked.connect(self._on_show_folder_clicked)
        self.compare_btn = QPushButton("📊 Compare Side-by-Side")
        self.compare_btn.clicked.connect(self._on_compare_clicked)
        self.trash_btn = QPushButton("🗑 Move to Trash")
        self.trash_btn.setStyleSheet("color: #ff5555;")
        self.trash_btn.clicked.connect(self._on_trash_clicked)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        actions.addWidget(self.open_btn)
        actions.addWidget(self.folder_btn)
        actions.addWidget(self.compare_btn)
        actions.addWidget(self.trash_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self.open_btn.setEnabled(False)
        self.folder_btn.setEnabled(False)
        self.compare_btn.setEnabled(False)
        self.trash_btn.setEnabled(False)

    # ------------------------------------------------------------------ #
    def _populate(self) -> None:
        self.results_list.clear()
        if not self._similar and not self._related:
            self.status_label.setText(
                "No similar files found. Run 'Index for AI' on the folder first, "
                "or try a file with more content."
            )
            return

        count = len(self._similar) + len(self._related)
        self.status_label.setText(f"{count} result(s)")

        for r in self._similar:
            pct = int(round(r.score * 100))
            bucket = f"Very Similar (Near Duplicate: {pct}% Match)" if pct >= 85 else f"Similar: {pct}% Match"
            tag_badge = "🔥 HIGH SIMILARITY" if pct >= 85 else "✨ MATCH"
            label = (
                f"🔁 [{bucket}] {os.path.basename(r.file_path)}\n"
                f"    Path: {r.file_path}\n"
                f"    Similarity: {pct}% · {r.matched_chunks} matched chunk(s) · {r.reason}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r.file_path)
            item.setData(Qt.UserRole + 1, "similar")
            item.setData(Qt.UserRole + 2, pct)
            self.results_list.addItem(item)

        for r in self._related:
            pct = int(round(r.score * 100)) if r.score else 60
            label = (
                f"🔗 [Related: {pct}% Match] {os.path.basename(r.file_path)}\n"
                f"    Path: {r.file_path}\n"
                f"    Similarity: {pct}% · Source: {r.source} · {r.reason}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r.file_path)
            item.setData(Qt.UserRole + 1, "related")
            item.setData(Qt.UserRole + 2, pct)
            self.results_list.addItem(item)

    # ------------------------------------------------------------------ #
    def _current_path(self) -> Optional[str]:
        item = self.results_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _on_selection_changed(self) -> None:
        item = self.results_list.currentItem()
        has_sel = item is not None
        self.open_btn.setEnabled(has_sel)
        self.folder_btn.setEnabled(has_sel)
        self.compare_btn.setEnabled(has_sel)

        if has_sel:
            pct = item.data(Qt.UserRole + 2) or 0
            # Enable deletion suggestion for high similarity near duplicates
            self.trash_btn.setEnabled(pct >= 85)
            if pct >= 85:
                self.trash_btn.setText(f"🗑 Move Redundant Copy ({pct}%) to Trash")
            else:
                self.trash_btn.setText("🗑 Move to Trash")
        else:
            self.trash_btn.setEnabled(False)

    def _on_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.file_open_requested.emit(path)
            if self._on_open is not None:
                self._on_open(path)

    def _on_open_clicked(self) -> None:
        path = self._current_path()
        if path:
            self.file_open_requested.emit(path)
            if self._on_open is not None:
                self._on_open(path)

    def _on_show_folder_clicked(self) -> None:
        path = self._current_path()
        if path:
            self.show_in_folder_requested.emit(os.path.dirname(path))

    def _on_compare_clicked(self) -> None:
        path = self._current_path()
        if path and self._source:
            self.compare_requested.emit(self._source, path)
            if self._on_compare is not None:
                self._on_compare(self._source, path)

    def _on_trash_clicked(self) -> None:
        path = self._current_path()
        if not path:
            return

        from PySide6.QtWidgets import QMessageBox
        pct = 0
        item = self.results_list.currentItem()
        if item:
            pct = item.data(Qt.UserRole + 2) or 0

        reply = QMessageBox.question(
            self,
            "Move Redundant Duplicate to Trash",
            f"Are you sure you want to move this file ({pct}% similarity) to the app trash?\n\n"
            f"File: {path}\n\n"
            f"Original: {self._source}",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.trash_requested.emit(path)
            if self._on_trash is not None:
                self._on_trash(path)
            # Remove item from list
            row = self.results_list.currentRow()
            if row >= 0:
                self.results_list.takeItem(row)

