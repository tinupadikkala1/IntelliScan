"""Knowledge Graph Dialog — File-Centric Content Relationship Graph.

Each file in the active folder is represented as a single Entity Node.
Pairwise content relationship degrees (percentages, e.g. 45%, 78%) are displayed
on the middle of connecting lines.
Files with no content relationships remain as disconnected nodes.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from graph.file_graph_builder import FileGraphBuilder
from graph.graph_query_service import GraphQueryService

logger = logging.getLogger(__name__)


class GraphDialog(QDialog):
    """File-centric Knowledge Graph exploration dialog."""

    evidence_activated = Signal(str, int)  # file_path, source_index

    def __init__(
        self,
        query_service: GraphQueryService,
        folder_path: str = "",
        retrieval=None,
        on_evidence_navigate: Optional[Callable[[str, dict], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._query = query_service
        self._folder_path = folder_path
        self._retrieval = retrieval
        self._on_evidence_navigate = on_evidence_navigate
        self._entities: List[dict] = []
        self._relationships: List[dict] = []

        self.setWindowTitle("Knowledge Graph — File Relationships")
        self.setMinimumSize(1020, 640)
        self.setModal(False)
        self._setup_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Toolbar
        toolbar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter files by name…")
        self.search_input.textChanged.connect(self._on_search)
        self.search_input.returnPressed.connect(self._on_search)
        toolbar.addWidget(self.search_input, 3)

        refresh_btn = QPushButton("Refresh Graph")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #64748b; font-weight: bold; padding-left: 10px;")
        toolbar.addWidget(self.stats_label)
        layout.addLayout(toolbar)


        splitter = QSplitter(Qt.Horizontal)

        # Left: Graph canvas
        canvas_group = QGroupBox("File Relationship Structure")
        canvas_layout = QVBoxLayout(canvas_group)
        from graph.graph_view import GraphView

        self.canvas = GraphView(
            on_entity_selected=self._on_entity_selected,
            on_evidence_activated=None,
        )
        canvas_layout.addWidget(self.canvas)
        splitter.addWidget(canvas_group)

        # Right: Details panel
        details_group = QGroupBox("Selected File Details")
        details_layout = QVBoxLayout(details_group)
        
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        details_layout.addWidget(self.details_text, 2)

        rel_group = QGroupBox("Connected File Relationships (%)")
        rel_layout = QVBoxLayout(rel_group)
        self.relationships_list = QListWidget()
        self.relationships_list.setAlternatingRowColors(True)
        self.relationships_list.itemClicked.connect(self._on_relationship_clicked)
        rel_layout.addWidget(self.relationships_list)
        details_layout.addWidget(rel_group, 2)

        evidence_group = QGroupBox("File Navigation")
        evidence_layout = QVBoxLayout(evidence_group)
        self.evidence_list = QListWidget()
        self.evidence_list.setAlternatingRowColors(True)
        self.evidence_list.setToolTip("Double-click to open/preview this file")
        self.evidence_list.itemDoubleClicked.connect(self._on_evidence_activated)
        evidence_layout.addWidget(self.evidence_list)
        details_layout.addWidget(evidence_group, 1)

        splitter.addWidget(details_group)
        splitter.setSizes([650, 370])
        layout.addWidget(splitter)

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        """Build and render the file-centric relationship graph."""
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        folder = self._folder_path
        if not folder and hasattr(self.parent(), "current_path"):
            folder = getattr(self.parent(), "current_path", "")
        if not folder and hasattr(self.parent(), "current_folder"):
            folder = getattr(self.parent(), "current_folder", "")
        if not folder:
            import os
            folder = os.getcwd()

        evidence_map = getattr(self._retrieval, "_evidence", {}) if self._retrieval else {}
        graph_data = FileGraphBuilder.build_file_graph(folder, evidence_map=evidence_map)

        self._entities = graph_data.get("entities", [])
        self._relationships = graph_data.get("relationships", [])

        self.canvas.set_graph(self._entities, self._relationships)
        self.stats_label.setText(
            f"{len(self._entities)} files · {len(self._relationships)} relationship edges"
        )
        if self._entities:
            self._on_entity_selected(self._entities[0])
        else:
            self.details_text.setPlainText("No files found in the active directory.")


    # ------------------------------------------------------------------ #
    def _on_search(self) -> None:
        query = self.search_input.text().strip().lower()
        if not query:
            self.canvas.set_graph(self._entities, self._relationships)
            return

        filtered_entities = [e for e in self._entities if query in e["name"].lower()]
        filtered_ids = {e["id"] for e in filtered_entities}
        filtered_rels = [
            r for r in self._relationships
            if r["source_id"] in filtered_ids and r["target_id"] in filtered_ids
        ]
        self.canvas.set_graph(filtered_entities, filtered_rels)
        self.stats_label.setText(
            f"Filtered: {len(filtered_entities)}/{len(self._entities)} files"
        )

    def _on_entity_selected(self, entity: dict) -> None:
        fname = entity.get("name", "")
        fpath = entity.get("file_path", "")
        ftype = entity.get("type", "DOCUMENT")
        fsize = entity.get("size", "")

        # Find all relationships connected to this file
        connected_rels = [
            r for r in self._relationships
            if r.get("source_id") == entity.get("id") or r.get("target_id") == entity.get("id")
        ]

        details = [
            f"📁 File: {fname}",
            f"Type: {ftype}",
            f"Size: {fsize}",
            f"Path: {fpath}",
            f"\n🔗 Connected Content Relationships ({len(connected_rels)}):",
        ]

        self.relationships_list.clear()
        for rel in connected_rels:
            is_src = rel.get("source_id") == entity.get("id")
            other_id = rel.get("target_id") if is_src else rel.get("source_id")
            other_node = next((n for n in self._entities if n["id"] == other_id), None)
            other_name = other_node["name"] if other_node else "Unknown"
            pct = rel.get("relation") or f"{rel.get('percentage', 0)}%"

            details.append(f"  • {pct} overlap with {other_name}")
            label = f"{fname} <── [{pct}] ──> {other_name}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, {"other_path": other_node.get("file_path", "") if other_node else "", "pct": pct})
            self.relationships_list.addItem(item)

        if not connected_rels:
            details.append("  (No content similarity with other files — disconnected node)")

        self.details_text.setPlainText("\n".join(details))

        self.evidence_list.clear()
        item = QListWidgetItem(f"📄 Open File: {fname}")
        item.setData(Qt.UserRole, {"evidence": {"file_path": fpath, "source_index": 0}})
        self.evidence_list.addItem(item)

    def _on_relationship_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole) or {}
        other_path = data.get("other_path", "")
        if other_path:
            fname = os.path.basename(other_path)
            self.details_text.append(f"\nClick double-click below to jump to connected file: {fname}")
            e_item = QListWidgetItem(f"📄 Connected File: {fname}")
            e_item.setData(Qt.UserRole, {"evidence": {"file_path": other_path, "source_index": 0}})
            self.evidence_list.addItem(e_item)

    def _on_evidence_activated(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole) or {}
        evidence = data.get("evidence", {})
        file_path = evidence.get("file_path", "")
        if not file_path:
            return
        if self._on_evidence_navigate is not None:
            self._on_evidence_navigate(file_path, evidence)
            return
        self.evidence_activated.emit(file_path, evidence.get("source_index", 0))
