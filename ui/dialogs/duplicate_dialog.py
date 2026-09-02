"""Duplicate Files dialog — B5-04 / B6-04.

Entry: Tools → Duplicate Files (workspace-wide), or right-click file →
AI → Find Duplicates (group containing the selected file).

Displays exact duplicate groups (same SHA-256) with per-file actions:
Open, Show in folder, Copy path. Batch 6 adds a *safe removal suggestion*
panel per group: which copy to keep, which to remove, why, and the
confidence. Accepting moves the file to the reversible app trash — nothing
is ever permanently deleted without explicit user confirmation.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from services.batch5_models import DuplicateGroup, DuplicateRemovalSuggestion


class DuplicateDialog(QDialog):
    """Shows exact duplicate groups with actions + safe removal suggestions."""

    file_open_requested = Signal(str)
    show_in_folder_requested = Signal(str)
    compare_requested = Signal(str, str)  # (file_a, file_b)
    removal_changed = Signal()

    def __init__(
        self,
        groups: Optional[List[DuplicateGroup]] = None,
        file_path: Optional[str] = None,
        on_open: Optional[Callable[[str], None]] = None,
        on_compare: Optional[Callable[[str, str], None]] = None,
        removal_suggestions: Optional[List[DuplicateRemovalSuggestion]] = None,
        on_removal_accept: Optional[Callable[[int], dict]] = None,
        on_removal_dismiss: Optional[Callable[[int], bool]] = None,
        is_loading: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._groups = groups or []
        self._file_path = file_path
        self._on_open = on_open
        self._on_compare = on_compare
        self._removal_suggestions = removal_suggestions or []

        self._on_removal_accept = on_removal_accept
        self._on_removal_dismiss = on_removal_dismiss
        self._current_group: Optional[DuplicateGroup] = None
        self._is_loading = is_loading

        self.setWindowTitle("Duplicate Files")
        self.setMinimumSize(700, 560)
        self.setModal(False)
        self._setup_ui()
        if self._is_loading:
            self.set_loading(True)
        else:
            self._populate()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-weight: bold; padding: 4px;")
        header.addWidget(self.summary_label)
        header.addStretch(1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        # Group selector
        self.group_combo_label = QLabel("Duplicate groups:")
        layout.addWidget(self.group_combo_label)
        self.group_list = QListWidget()
        self.group_list.itemSelectionChanged.connect(self._on_group_selected)
        layout.addWidget(self.group_list, 1)

        # Files in group
        files_label = QLabel("Files in group:")
        layout.addWidget(files_label)
        self.files_list = QListWidget()
        self.files_list.setAlternatingRowColors(True)
        self.files_list.itemDoubleClicked.connect(self._on_file_activated)
        self.files_list.itemSelectionChanged.connect(self._on_file_selection_changed)
        layout.addWidget(self.files_list, 2)

        # Batch 6 §9.5 — safe removal suggestion panel
        self.suggestion_box = QLabel("")
        self.suggestion_box.setWordWrap(True)
        self.suggestion_box.setTextInteractionFlags(
            self.suggestion_box.textInteractionFlags().TextSelectableByMouse
        )
        self.suggestion_box.setStyleSheet(
            "padding: 8px; background: #222; border-radius: 6px; color: #ddd;"
        )
        layout.addWidget(self.suggestion_box)
        removal_actions = QHBoxLayout()
        self.accept_removal_btn = QPushButton("🗑 Accept Removal (to trash)")
        self.accept_removal_btn.setToolTip(
            "Moves the redundant copy into the app trash (reversible). "
            "You will be asked to confirm first."
        )
        self.accept_removal_btn.clicked.connect(self._on_accept_removal)
        self.dismiss_removal_btn = QPushButton("Dismiss")
        self.dismiss_removal_btn.clicked.connect(self._on_dismiss_removal)
        removal_actions.addWidget(self.accept_removal_btn)
        removal_actions.addWidget(self.dismiss_removal_btn)
        removal_actions.addStretch(1)
        layout.addLayout(removal_actions)
        self.accept_removal_btn.setEnabled(False)
        self.dismiss_removal_btn.setEnabled(False)

        # Actions
        actions = QHBoxLayout()
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(self._on_open_clicked)
        self.folder_btn = QPushButton("Show in folder")
        self.folder_btn.clicked.connect(self._on_show_folder_clicked)
        self.copy_btn = QPushButton("Copy path")
        self.copy_btn.clicked.connect(self._on_copy_path_clicked)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(self.open_btn)
        actions.addWidget(self.folder_btn)
        actions.addWidget(self.copy_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self.open_btn.setEnabled(False)
        self.folder_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)


    # ------------------------------------------------------------------ #
    def set_loading(self, is_loading: bool, message: str = "") -> None:
        """Toggle loading state while duplicate scan runs asynchronously."""
        self._is_loading = is_loading
        if is_loading:
            self.summary_label.setText("⏳ Scanning folder for exact & near duplicate files...")
            self.suggestion_box.setText(
                message or "Searching files, calculating SHA-256 fingerprints and content vector similarity..."
            )
            self.group_list.clear()
            loading_item = QListWidgetItem("⏳ Scanning in progress... Please wait.")
            loading_item.setFlags(Qt.NoItemFlags)
            self.group_list.addItem(loading_item)
            self.files_list.clear()
            self.open_btn.setEnabled(False)
            self.folder_btn.setEnabled(False)
            self.copy_btn.setEnabled(False)
            self.refresh_btn.setEnabled(False)
        else:
            self.refresh_btn.setEnabled(True)

    def set_results(
        self,
        groups: List[DuplicateGroup],
        removal_suggestions: Optional[List[DuplicateRemovalSuggestion]] = None,
    ) -> None:
        """Populate dialog dynamically once background scan completes."""
        self._groups = groups or []
        self._removal_suggestions = removal_suggestions or []
        self.set_loading(False)
        self._populate()

    # ------------------------------------------------------------------ #
    def _populate(self) -> None:
        if not self._groups:
            self.summary_label.setText("No duplicate files found.")
            self.group_list.clear()
            self.files_list.clear()
            return

        empty_count = sum(1 for g in self._groups if g.is_empty)
        self.summary_label.setText(
            f"{len(self._groups)} duplicate group(s) · "
            f"{sum(len(g.files) for g in self._groups)} files"
        )

        self.group_list.clear()
        for g in self._groups:
            if g.is_empty:
                label = f"Empty-content duplicates ({len(g.files)} files)"
            elif getattr(g, "checksum", "").startswith("near_"):
                parts = g.checksum.split("_")
                sim_pct = parts[1] if len(parts) > 1 else "Near"
                label = f"🔁 {len(g.files)} files · Near Duplicate ({sim_pct}% Content Similarity)"
            else:
                label = f"✨ {len(g.files)} copies · Exact Duplicate (100% Match) · {g.checksum[:12]}…"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, id(g))
            self.group_list.addItem(item)

        # Auto-select the group containing the selected file if provided.
        if self._file_path:
            for g in self._groups:
                if any(os.path.abspath(p) == os.path.abspath(self._file_path) for p in g.files):
                    self._select_group(g)
                    return
        if self._groups:
            self._select_group(self._groups[0])

    def _select_group(self, group: DuplicateGroup) -> None:
        self._current_group = group
        self.files_list.clear()
        for path in group.files:
            item = QListWidgetItem(path)
            item.setData(Qt.UserRole, path)
            self.files_list.addItem(item)
        if self.files_list.count() > 0:
            self.files_list.setCurrentRow(0)
        has_file = self.files_list.count() > 0
        self.open_btn.setEnabled(has_file)
        self.folder_btn.setEnabled(has_file)
        self.copy_btn.setEnabled(has_file)
        self._show_removal_suggestion(group)
        # Keep the group list highlight in sync.
        for i in range(self.group_list.count()):
            if self.group_list.item(i).data(Qt.UserRole) == id(group):
                self.group_list.setCurrentRow(i)
                break

    # ------------------------------------------------------------------ #
    # Batch 6 §9.5 — removal suggestions
    # ------------------------------------------------------------------ #
    def _suggestion_for_group(self, group: DuplicateGroup) -> Optional[DuplicateRemovalSuggestion]:
        """First pending suggestion whose group checksum matches."""
        checksum = getattr(group, "checksum", "") or ""
        for s in self._removal_suggestions:
            if s.group_checksum == checksum and s.status == "pending":
                return s
        return None

    def _show_removal_suggestion(self, group: DuplicateGroup) -> None:
        self._current_removal: Optional[DuplicateRemovalSuggestion] = None
        suggestion = self._suggestion_for_group(group)
        if suggestion is None:
            self.suggestion_box.setText(
                "No removal suggestion for this group (generate one from "
                "Tools → Duplicate Files to review safe removals)."
            )
            self.accept_removal_btn.setEnabled(False)
            self.dismiss_removal_btn.setEnabled(False)
            return
        self._current_removal = suggestion
        self.suggestion_box.setText(
            f"Removal suggestion ({suggestion.duplicate_type}):\n"
            f"  Keep:    {suggestion.keep_path}\n"
            f"  Remove:  {suggestion.remove_path}\n"
            f"  Reason:  {suggestion.reason}\n"
            f"  Confidence: {suggestion.confidence:.0%}"
        )
        self.accept_removal_btn.setEnabled(True)
        self.dismiss_removal_btn.setEnabled(True)

    def _on_accept_removal(self) -> None:
        suggestion = self._current_removal
        if suggestion is None:
            return
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "Remove Duplicate",
            f"Move this file to the app trash (reversible)?\n\n"
            f"{suggestion.remove_path}\n\n"
            f"Keep: {suggestion.keep_path}\n"
            f"Reason: {suggestion.reason}",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if self._on_removal_accept is None:
            QMessageBox.information(self, "Remove Duplicate",
                                    "Removal is not available in this context.")
            return
        result = self._on_removal_accept(suggestion.id) or {}
        if result.get("ok"):
            suggestion.status = "executed"
            self.suggestion_box.setText(
                f"✓ Moved to trash: {result.get('trash_path', '')}"
            )
            self.accept_removal_btn.setEnabled(False)
            self.dismiss_removal_btn.setEnabled(False)
            self.removal_changed.emit()
            self.refresh()
        else:
            QMessageBox.warning(self, "Remove Duplicate",
                                result.get("error", "Removal failed."))

    def _on_dismiss_removal(self) -> None:
        suggestion = self._current_removal
        if suggestion is None:
            return
        if self._on_removal_dismiss:
            self._on_removal_dismiss(suggestion.id)
        suggestion.status = "dismissed"
        self.suggestion_box.setText("Suggestion dismissed. No file was changed.")
        self.accept_removal_btn.setEnabled(False)
        self.dismiss_removal_btn.setEnabled(False)
        self.removal_changed.emit()

    def _on_group_selected(self) -> None:
        row = self.group_list.currentRow()
        if row < 0 or row >= len(self._groups):
            return
        self._select_group(self._groups[row])

    def refresh(self) -> None:
        """Re-query duplicate groups (data may have changed)."""
        self._populate()

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    def _current_path(self) -> Optional[str]:
        item = self.files_list.currentItem()
        if item and item.data(Qt.UserRole):
            return item.data(Qt.UserRole)
        if self._current_group and self._current_group.files:
            return self._current_group.files[0]
        return None

    def _on_file_selection_changed(self) -> None:
        has_path = self._current_path() is not None
        self.open_btn.setEnabled(has_path)
        self.folder_btn.setEnabled(has_path)
        self.copy_btn.setEnabled(has_path)

    def _on_file_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self._emit_open(path)

    def _on_open_clicked(self) -> None:
        path = self._current_path()
        if path:
            self._emit_open(path)

    def _emit_open(self, path: str) -> None:
        self.file_open_requested.emit(path)
        if self._on_open is not None:
            self._on_open(path)

    def _on_show_folder_clicked(self) -> None:
        path = self._current_path()
        if path:
            folder = os.path.dirname(path)
            if os.path.exists(folder):
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            self.show_in_folder_requested.emit(folder)

    def _on_compare_clicked(self) -> None:
        if not self._current_group or len(self._current_group.files) < 2:
            return
        path_a = self._current_path() or self._current_group.files[0]
        # Pick another file in group to compare with
        path_b = next((p for p in self._current_group.files if p != path_a), self._current_group.files[1])

        self.compare_requested.emit(path_a, path_b)
        if self._on_compare is not None:
            self._on_compare(path_a, path_b)

    def _on_copy_path_clicked(self) -> None:
        path = self._current_path()
        if path:
            QGuiApplication.clipboard().setText(path)

