"""Inactive Files Reminder Dialog.

Displays a list of files that have not been opened or accessed for a user-specified
number of days (e.g., 7, 14, 28 days). Allows users to open inactive files directly,
organize them into a new folder, or dismiss the alert.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from services.inactivity_reminder_service import InactiveFileInfo, InactivityReminderService


class InactiveFilesDialog(QDialog):
    """Dialog alerting the user about inactive files."""

    file_open_requested = Signal(str)
    organize_requested = Signal(list)  # list of file paths

    def __init__(
        self,
        inactive_files: List[InactiveFileInfo],
        threshold_days: int = 14,
        on_open: Optional[Callable[[str], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._inactive_files = inactive_files or []
        self._threshold_days = threshold_days
        self._on_open = on_open

        self.setWindowTitle("🔔 Inactive Files Reminder")
        self.setMinimumSize(800, 520)
        self.setModal(False)
        self._setup_ui()
        self._populate()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Banner
        self.banner_label = QLabel(
            f"<b>🔔 Inactive File Reminder:</b> Found {len(self._inactive_files)} file(s) "
            f"that have not been opened in over {self._threshold_days} day(s)."
        )
        self.banner_label.setStyleSheet(
            "padding: 8px; background: #2a2a3a; border-radius: 6px; color: #7cb5ec; font-size: 13px;"
        )
        self.banner_label.setWordWrap(True)
        layout.addWidget(self.banner_label)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["File Name", "Days Inactive", "Introduced Date", "Last Opened", "Path"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 200)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._on_activated)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)

        # Bottom Actions
        actions = QHBoxLayout()
        self.open_btn = QPushButton("📄 Open Selected File")
        self.open_btn.setStyleSheet("font-weight: bold; padding: 6px 14px;")
        self.open_btn.clicked.connect(self._on_open_clicked)
        self.open_btn.setEnabled(False)

        self.organize_btn = QPushButton("📁 Organize Files into Folder...")
        self.organize_btn.clicked.connect(self._on_organize_clicked)

        close_btn = QPushButton("Dismiss")
        close_btn.clicked.connect(self.accept)

        actions.addWidget(self.open_btn)
        actions.addWidget(self.organize_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    def _populate(self) -> None:
        self.table.setRowCount(0)
        for row_idx, item in enumerate(self._inactive_files):
            self.table.insertRow(row_idx)

            # Name
            name_item = QTableWidgetItem(item.file_name)
            name_item.setData(Qt.UserRole, item.file_path)
            self.table.setItem(row_idx, 0, name_item)

            # Days inactive badge
            days_item = QTableWidgetItem(f"{item.days_inactive} days")
            days_item.setTextAlignment(Qt.AlignCenter)
            if item.days_inactive >= 30:
                days_item.setForeground(Qt.red)
            elif item.days_inactive >= 14:
                days_item.setForeground(Qt.darkYellow)
            self.table.setItem(row_idx, 1, days_item)

            # Introduced date
            intro_item = QTableWidgetItem(item.introduced_date)
            intro_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 2, intro_item)

            # Last opened
            opened_item = QTableWidgetItem(item.last_opened)
            opened_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 3, opened_item)

            # Path
            path_item = QTableWidgetItem(item.file_path)
            self.table.setItem(row_idx, 4, path_item)

    def _current_path(self) -> Optional[str]:
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 0)
            if item:
                return item.data(Qt.UserRole)
        return None

    def _on_selection_changed(self) -> None:
        self.open_btn.setEnabled(self._current_path() is not None)

    def _on_activated(self, row: int, col: int) -> None:
        item = self.table.item(row, 0)
        if item:
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

    def _on_organize_clicked(self) -> None:
        paths = [item.file_path for item in self._inactive_files if os.path.exists(item.file_path)]
        if not paths:
            QMessageBox.information(self, "Organize Files", "No active files available to organize.")
            return
        self.organize_requested.emit(paths)
