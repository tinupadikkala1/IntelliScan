"""Workspace Knowledge Dashboard — B5-10.

Entry: Tools → Knowledge Dashboard.

Aggregates file / AI / semantic / duplicate / relationship / collection /
graph statistics. Empty states explicitly say "AI indexing has not been
performed yet" instead of showing misleading zeros.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from services.dashboard_service import DashboardService


class DashboardDialog(QDialog):
    """Shows the workspace knowledge dashboard."""

    refresh_requested = Signal()
    file_open_requested = Signal(str)

    def __init__(
        self,
        service: DashboardService,
        folder_path: Optional[str] = None,
        on_open: Optional[Callable[[str], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._folder_path = folder_path
        self._on_open = on_open

        self.setWindowTitle("Knowledge Dashboard")
        self.setMinimumSize(860, 620)
        self.setModal(False)
        self._setup_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        title_text = "📊 Workspace Knowledge Dashboard"
        if self._folder_path:
            import os
            title_text += f" ({os.path.basename(self._folder_path)})"
        title = QLabel(title_text)
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        toolbar.addWidget(title)
        toolbar.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        grid = QGridLayout()

        self.files_box = self._metric_box("Files")
        self.ai_box = self._metric_box("AI Analysis")
        self.semantic_box = self._metric_box("Semantic Index")
        self.dup_box = self._metric_box("Duplicates")
        self.rel_box = self._metric_box("File Relationships")
        self.col_box = self._metric_box("Collections")
        self.graph_box = self._metric_box("Knowledge Graph")
        self.system_box = self._metric_box("System")

        grid.addWidget(self.files_box, 0, 0)
        grid.addWidget(self.ai_box, 0, 1)
        grid.addWidget(self.semantic_box, 0, 2)
        grid.addWidget(self.dup_box, 0, 3)
        grid.addWidget(self.rel_box, 1, 0)
        grid.addWidget(self.col_box, 1, 1)
        grid.addWidget(self.graph_box, 1, 2)
        grid.addWidget(self.system_box, 1, 3)
        layout.addLayout(grid)

        # Categories + tags detail
        detail_group = QGroupBox("Categories & Top Tags")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        detail_layout.addWidget(self.detail_text)
        layout.addWidget(detail_group, 1)

        # Recent files
        recent_group = QGroupBox("Recently Modified")
        recent_layout = QVBoxLayout(recent_group)
        self.recent_list = QListWidget()
        self.recent_list.setAlternatingRowColors(True)
        self.recent_list.itemDoubleClicked.connect(self._on_recent_activated)
        recent_layout.addWidget(self.recent_list)
        layout.addWidget(recent_group, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _metric_box(title: str) -> QGroupBox:
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        label = QLabel("—")
        label.setStyleSheet("font-size: 15px; font-weight: bold;")
        label.setWordWrap(True)
        v.addWidget(label)
        return box

    def _set_metric(self, box: QGroupBox, text: str) -> None:
        label = box.layout().itemAt(0).widget()
        label.setText(text)

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        try:
            snap = self._service.snapshot(folder_path=self._folder_path)
        except Exception as exc:
            self._set_metric(self.files_box, f"Error: {exc}")
            return

        files = snap["files"]
        self._set_metric(
            self.files_box,
            f"{files['total']} indexed\n"
            f"{len(files['by_extension'])} extensions\n"
            f"{len(files['by_type'])} types",
        )

        ai = snap["ai"]
        ai_indexed = snap["semantic"].get("ai_indexed_files", 0)
        if ai_indexed == 0 and ai.get("total_indexed", 0) > 0:
            self._set_metric(
                self.ai_box,
                "AI indexing has not been performed yet.\nRun \"Index for AI\" "
                "to populate semantic statistics.",
            )
        else:
            self._set_metric(
                self.ai_box,
                f"{ai.get('analyzed', 0)} analyzed\n"
                f"{ai.get('unanalyzed', 0)} unanalyzed\n"
                f"{len(ai.get('categories', {}))} categories",
            )

        sem = snap["semantic"]
        self._set_metric(
            self.semantic_box,
            f"{sem.get('ai_indexed_files', 0)} AI-indexed files\n"
            f"{sem.get('evidence_chunks', 0)} evidence chunks\n"
            f"{sem.get('vectors', 0)} vectors\n"
            f"{sem.get('recent_searches', 0)} searches logged",
        )

        dup = snap["duplicates"]
        self._set_metric(
            self.dup_box,
            f"{dup.get('groups', 0)} group(s)\n"
            f"{dup.get('duplicate_files', 0)} duplicate files\n"
            f"{dup.get('extra_copies_bytes', 0):,} B wasted",
        )

        rel = snap["relationships"]
        by_type = rel.get("by_type", {})
        self._set_metric(
            self.rel_box,
            f"{rel.get('total', 0)} relationship(s)\n" +
            "\n".join(f"  {k}: {v}" for k, v in list(by_type.items())[:4]),
        )

        col = snap["collections"]
        self._set_metric(
            self.col_box,
            f"{col.get('total', 0)} total\n"
            f"{col.get('static', 0)} static · {col.get('smart', 0)} smart\n"
            f"{col.get('members', 0)} members",
        )

        graph = snap["graph"]
        self._set_metric(
            self.graph_box,
            f"{graph.get('entities', 0)} entities\n"
            f"{graph.get('relationships', 0)} relationships\n"
            f"{graph.get('evidence_links', 0)} evidence links",
        )

        sys_stats = snap["system"]
        self._set_metric(
            self.system_box,
            f"Pending index: {sys_stats.get('indexing_pending', 0)}\n"
            f"Failed index: {sys_stats.get('indexing_failed', 0)}\n"
            f"AI index available: {'yes' if sys_stats.get('ai_index_available') else 'no'}",
        )

        # Category + tag detail
        cats = ai.get("categories", {})
        tag_rows = self._service._tagger.tags_in_workspace(limit=12) if self._service._tagger else []
        detail_lines = []
        if cats:
            detail_lines.append("Categories:")
            for cat, count in sorted(cats.items(), key=lambda kv: kv[1], reverse=True):
                detail_lines.append(f"  {cat}: {count}")
        else:
            detail_lines.append("No classified files yet — use AI → Classify.")
        detail_lines.append("")
        if tag_rows:
            detail_lines.append("Top tags:")
            detail_lines.append(
                "  " + " · ".join(f"{t['tag']} ({t['count']})" for t in tag_rows[:10])
            )
        else:
            detail_lines.append("No tags yet — use AI → Auto-Tag.")
        self.detail_text.setPlainText("\n".join(detail_lines))

        # Recent files
        self.recent_list.clear()
        for r in snap.get("recent", []):
            item = QListWidgetItem(f"{r['filename']}  ·  {r['modified']}\n    {r['path']}")
            item.setData(Qt.UserRole, r["path"])
            self.recent_list.addItem(item)

        self.refresh_requested.emit()

    def _on_recent_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.file_open_requested.emit(path)
            if self._on_open is not None:
                self._on_open(path)
