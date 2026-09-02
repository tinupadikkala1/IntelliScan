"""Organization Preview dialog — B6-05 (#29).

Shows the exact file → folder mapping the user is about to approve and
requires explicit approval before anything moves:

    document1.pdf
      Current: /Downloads/
      Target:  /Documents/Academic/

[Approve All] [Approve Selected] [Cancel]

Nothing moves unless approved. Collisions are surfaced as failures in the
result report, never silently overwritten.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

# move_spec: (source_path, target_dir, display_name)
MoveSpec = tuple


class OrganizationPreviewDialog(QDialog):
    """Preview + approve an explicit set of file moves."""

    def __init__(
        self,
        moves: List[MoveSpec],
        on_execute: Optional[Callable[[str, str], str]] = None,
        parent=None,
    ) -> None:
        """Args:
            moves: list of (source_path, target_dir) tuples.
            on_execute: callable(src, dst_dir) → error string or "" on success.
        """
        super().__init__(parent)
        self._moves = moves
        self._on_execute = on_execute
        self._approved: List[MoveSpec] = []

        self.setWindowTitle("Organization Preview")
        self.setMinimumSize(640, 460)
        self.setModal(True)
        self._setup_ui()
        self._populate()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        note = QLabel(
            "Review the moves below. Files are only moved after you explicitly "
            "approve — nothing is moved or overwritten automatically."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; padding: 4px;")
        layout.addWidget(note)

        self.moves_list = QListWidget()
        self.moves_list.setAlternatingRowColors(True)
        self.moves_list.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.moves_list, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; padding: 2px;")
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.approve_all_btn = QPushButton("✓ Approve All")
        self.approve_all_btn.clicked.connect(self._on_approve_all)
        self.approve_sel_btn = QPushButton("Approve Selected")
        self.approve_sel_btn.clicked.connect(self._on_approve_selected)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(self.approve_all_btn)
        actions.addWidget(self.approve_sel_btn)
        actions.addStretch(1)
        actions.addWidget(cancel_btn)
        layout.addLayout(actions)

        self.approve_sel_btn.setEnabled(False)

    def _populate(self) -> None:
        self.moves_list.clear()
        for src, dst_dir in self._moves:
            text = (
                f"{os.path.basename(src)}\n"
                f"    Current: {os.path.dirname(src)}\n"
                f"    Target:  {dst_dir}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, (src, dst_dir))
            self.moves_list.addItem(item)
        self.status_label.setText(f"{len(self._moves)} move(s) pending approval")

    def _on_selection(self) -> None:
        self.approve_sel_btn.setEnabled(bool(self.moves_list.currentItem()))

    def _selected_moves(self) -> List[MoveSpec]:
        item = self.moves_list.currentItem()
        if item is None:
            return []
        return [item.data(Qt.UserRole)]

    # ------------------------------------------------------------------ #
    def _on_approve_all(self) -> None:
        reply = QMessageBox.question(
            self,
            "Approve Organization",
            f"Move {len(self._moves)} file(s) to their target folders? "
            "This is reversible — files are moved, never deleted.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._execute(list(self._moves))

    def _on_approve_selected(self) -> None:
        moves = self._selected_moves()
        if not moves:
            return
        self._execute(moves)

    def _execute(self, moves: List[MoveSpec]) -> None:
        if self._on_execute is None:
            self.status_label.setText("Move execution is not available in this context.")
            return
        ok = failed = 0
        failures = []
        for src, dst_dir in moves:
            try:
                error = self._on_execute(src, dst_dir)
                if error:
                    failed += 1
                    failures.append((os.path.basename(src), error))
                else:
                    ok += 1
                    self._mark_done(src, dst_dir)
            except Exception as exc:  # never crash the dialog
                failed += 1
                failures.append((os.path.basename(src), str(exc)))
        self.status_label.setText(
            f"{ok} moved · {failed} failed"
            if failed
            else f"{ok} file(s) moved ✓"
        )
        if failures:
            detail = "\n".join(f"• {name}: {err}" for name, err in failures[:6])
            QMessageBox.warning(self, "Organization", f"Some moves failed:\n\n{detail}")
        # Success feedback stays in the status label (non-modal); only
        # failures interrupt the user. This keeps the dialog non-blocking
        # in automated tests as well as normal use.

    def _mark_done(self, src: str, dst_dir: str) -> None:
        for i in range(self.moves_list.count()):
            item = self.moves_list.item(i)
            data = item.data(Qt.UserRole)
            if data and data[0] == src:
                item.setText(f"✓ {os.path.basename(src)} → {os.path.dirname(dst_dir)}")
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
