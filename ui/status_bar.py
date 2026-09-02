"""Status bar.

Shows the current item count, free disk space for the active volume and a
background-task indicator. Kept free of logic: callers push formatted text.
"""

from __future__ import annotations

import shutil

from PySide6.QtWidgets import QStatusBar, QLabel


class StatusBar(QStatusBar):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.item_label = QLabel("")
        self.space_label = QLabel("")
        self.task_label = QLabel("")
        self.addPermanentWidget(self.item_label)
        self.addPermanentWidget(self.space_label)
        self.addPermanentWidget(self.task_label)

    def set_item_count(self, count: int) -> None:
        self.item_label.setText(f"{count} item{'s' if count != 1 else ''}")

    def set_free_space(self, path: str) -> None:
        try:
            total, used, free = shutil.disk_usage(path)
            self.space_label.setText(f"Free: {free // (1024 ** 3)} GB")
        except OSError:
            self.space_label.setText("")

    def set_task_status(self, text: str) -> None:
        self.task_label.setText(text)
