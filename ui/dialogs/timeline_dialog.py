"""File Timeline dialog — B7-7 (#26).

Entry: Tools → File Timeline.

Chronological, grouped-by-day view of recorded file activity (created /
modified / opened). Filters: day range, folder, file type, event kind.
Double-clicking an event opens the file.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QComboBox,
    QVBoxLayout,
)


class TimelineDialog(QDialog):
    """Chronological view of file activity."""

    def __init__(
        self,
        service,
        folder: Optional[str] = None,
        open_file: Optional[Callable[[str], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._folder = folder
        self._open_file = open_file

        title = "File Timeline"
        if self._folder:
            title += f" ({os.path.basename(self._folder)})"
        self.setWindowTitle(title)
        self.resize(680, 520)
        self.setModal(False)
        self._setup_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        filters = QFormLayout()
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 365)
        self.days_spin.setValue(90)
        self.days_spin.valueChanged.connect(lambda _v: self.refresh())
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["All events", "Created", "Modified", "Opened"])
        self.kind_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        self.ext_combo = QComboBox()
        self.ext_combo.addItem("All file types", None)
        self.ext_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        filters.addRow("Show last", self.days_spin)
        filters.addRow("Event kind", self.kind_combo)
        filters.addRow("File type", self.ext_combo)
        layout.addLayout(filters)

        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_open)
        layout.addWidget(self.list_widget, 1)

        actions = QHBoxLayout()
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.refresh)
        self.export_btn = QPushButton("💾 Export Timeline...")
        self.export_btn.clicked.connect(self._on_export)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(refresh_btn)
        actions.addWidget(self.export_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        kinds = {
            "All events": None,
            "Created": ["created"],
            "Modified": ["modified"],
            "Opened": ["opened"],
        }[self.kind_combo.currentText()]
        ext = self.ext_combo.currentData()

        groups = self._service.grouped(
            days=self.days_spin.value(),
            folder=self._folder,
            kinds=kinds,
            extension=ext if ext else None,
            limit=2000,
        )
        self._current_groups = groups
        self.list_widget.clear()
        total = sum(g["count"] for g in groups)
        self.summary_label.setText(f"{total} events across {len(groups)} days")

        for group in groups:
            day_item = QListWidgetItem(f"── {group['day']}  ({group['count']} events) ──")
            day_item.setFlags(Qt.ItemIsEnabled)
            day_item.setForeground(Qt.gray)
            self.list_widget.addItem(day_item)
            for ev in group["events"]:
                time_str = ev["time"][11:19] if len(ev["time"]) >= 19 else ev["time"]
                text = f"[{ev['kind']}] {time_str}  {ev['filename']}"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, ev["path"])
                item.setToolTip(ev["path"])
                self.list_widget.addItem(item)

    def _on_export(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        groups = getattr(self, "_current_groups", [])
        if not groups:
            QMessageBox.information(self, "Export Timeline", "No timeline activity events to export.")
            return

        default_name = "timeline_export.csv"
        if self._folder:
            default_name = f"{os.path.basename(self._folder)}_timeline.csv"
        default_path = os.path.join(os.path.expanduser("~"), default_name)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Timeline Activity",
            default_path,
            "CSV Files (*.csv);;JSON Files (*.json)",
        )
        if not file_path:
            return

        try:
            success = self._service.export_timeline(groups, file_path)
            if success:
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Timeline activity successfully saved to:\n{file_path}",
                )
            else:
                QMessageBox.warning(self, "Export Failed", "Could not write timeline export file.")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", f"Failed to export timeline: {exc}")

    # ------------------------------------------------------------------ #
    def _on_open(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path and self._open_file is not None:
            self._open_file(path)
