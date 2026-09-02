"""Rename Preview dialog — B7-9 (#28).

Entry: File → AI → Suggest Rename (one or more files).

Shows Current → Proposed with validation status and reason; Approve
Selected / Approve All / Cancel. Execution reuses the approved-move path
(move_file with the same directory), so every derived layer stays in sync
and SHA-256 identity is preserved. Nothing renames without approval.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class RenamePreviewDialog(QDialog):
    """Preview and approve proposed file renames."""

    def __init__(
        self,
        suggestions: List,
        approve: Optional[Callable[[str, str], dict]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._suggestions = suggestions
        self._approve = approve  # fn(file_path, new_name) -> dict result
        self.setWindowTitle("Rename Preview")
        self.resize(720, 480)
        self.setModal(False)
        self._setup_ui()
        self._populate()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        note = QLabel(
            "Proposed names are derived from existing metadata. Nothing is "
            "renamed until you approve. Extension changes are never allowed."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; padding: 2px;")
        layout.addWidget(note)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Current Name", "Proposed Name", "Status"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.approve_selected_btn = QPushButton("Approve Selected")
        self.approve_selected_btn.clicked.connect(self._approve_selected)
        self.approve_all_btn = QPushButton("Approve All")
        self.approve_all_btn.clicked.connect(self._approve_all)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(self.approve_selected_btn)
        actions.addWidget(self.approve_all_btn)
        actions.addStretch(1)
        actions.addWidget(cancel_btn)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #
    def _populate(self) -> None:
        self.table.setRowCount(len(self._suggestions))
        for row, sug in enumerate(self._suggestions):
            self.table.setItem(row, 0, QTableWidgetItem(sug.current_name))
            self.table.setItem(row, 1, QTableWidgetItem(sug.proposed_name))
            if sug.errors:
                item = QTableWidgetItem("⚠ " + "; ".join(sug.errors[:2]))
                item.setForeground(Qt.red)
            else:
                item = QTableWidgetItem("ready")
                item.setForeground(Qt.green)
            self.table.setItem(row, 2, item)
            self.table.setRowHeight(row, 22)

    # ------------------------------------------------------------------ #
    def _approve_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            self.status_label.setText("Select at least one row to approve.")
            self.status_label.setStyleSheet("color: #e0a030;")
            return
        self._run([self._suggestions[r] for r in sorted(rows)])

    def _approve_all(self) -> None:
        self._run(list(self._suggestions))

    def _run(self, suggestions: List) -> None:
        if self._approve is None:
            self.status_label.setText("Rename execution is not available.")
            return
        done = 0
        failed = []
        for sug in suggestions:
            if sug.errors:
                failed.append(f"{sug.current_name}: {sug.errors[0]}")
                continue
            try:
                result = self._approve(sug.file_path, sug.proposed_name)
                if result and result.get("ok"):
                    done += 1
                else:
                    failed.append(f"{sug.current_name}: {result.get('error', 'failed') if result else 'failed'}")
            except Exception as exc:
                failed.append(f"{sug.current_name}: {exc}")
        if failed:
            self.status_label.setText(
                f"Renamed {done} file(s). Failures: " + "; ".join(failed[:3])
            )
            self.status_label.setStyleSheet("color: #c07030;")
        else:
            self.status_label.setText(f"✓ Renamed {done} file(s).")
            self.status_label.setStyleSheet("color: green;")
        self._populate()  # reflect any status changes
