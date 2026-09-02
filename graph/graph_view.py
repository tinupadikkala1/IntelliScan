"""Knowledge graph canvas — QGraphicsView rendering of entities + relationships.

Features:
- Draggable nodes: drag any node to reposition it; connected edges update dynamically.
- Smooth mouse wheel zoom in / out centered on cursor.
- Organic force-directed layout (Spring layout) so nodes are spacious instead of fixed in a rigid circle.
- Clean percentage edge badges placed dynamically in the middle of relationship lines.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

_TYPE_COLORS = {
    "DOCUMENT": "#3b82f6",  # Blue
    "IMAGE": "#10b981",     # Green
    "AUDIO": "#8b5cf6",     # Purple
    "VIDEO": "#f97316",     # Orange
    "CONCEPT": "#64748b",   # Slate Gray
    "OTHER": "#64748b",
}


class GraphNodeItem(QGraphicsEllipseItem):
    """Draggable ellipse node representing a file entity."""

    def __init__(self, entity: dict, radius: float = 34.0) -> None:
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.entity = entity
        self._radius = radius
        self._edges: List[GraphEdgeItem] = []

        color_hex = entity.get("color") or _TYPE_COLORS.get(entity.get("type", "DOCUMENT"), "#3b82f6")
        self._color = QColor(color_hex)
        self.setBrush(QBrush(self._color))
        self.setPen(QPen(QColor("#0f172a"), 2.0))

        # Enable dragging and geometry updates
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsScenePositionChanges, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptHoverEvents(True)

        label = QGraphicsSimpleTextItem(self)
        name = entity.get("name", "?")
        display = name if len(name) <= 50 else name[:47] + "…"

        label.setText(display)
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        label.setFont(font)
        label.setBrush(QBrush(QColor("#ffffff")))
        label.setPos(-label.boundingRect().width() / 2, -label.boundingRect().height() / 2)

        tt = f"File: {name}\nType: {entity.get('type', 'DOCUMENT')}"
        if entity.get("size"):
            tt += f"\nSize: {entity.get('size')}"
        self.setToolTip(tt)

    def add_edge(self, edge: GraphEdgeItem) -> None:
        if edge not in self._edges:
            self._edges.append(edge)

    def itemChange(self, change, value):  # noqa: N802 (Qt naming)
        if change == QGraphicsItem.ItemPositionHasChanged:
            for edge in self._edges:
                edge.update_positions()
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.setPen(QPen(QColor("#f59e0b"), 3.5))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.setPen(QPen(QColor("#0f172a"), 2.0))
        super().hoverLeaveEvent(event)


class GraphEdgeItem(QGraphicsLineItem):
    """Dynamic connecting line edge between two file nodes displaying relationship percentage in the middle."""

    def __init__(self, source_node: GraphNodeItem, target_node: GraphNodeItem, relationship: dict) -> None:
        super().__init__()
        self.source_node = source_node
        self.target_node = target_node
        self.relationship = relationship

        source_node.add_edge(self)
        target_node.add_edge(self)

        pct = relationship.get("percentage", 0)
        rel_text = str(relationship.get("relation", ""))
        if not rel_text or rel_text == "None":
            rel_text = f"{pct}%" if pct else "0%"
        elif rel_text.isdigit():
            rel_text = f"{rel_text}%"

        width = 1.5 + (pct / 100.0) * 2.5 if pct else 1.5
        pen = QPen(QColor("#3b82f6"), width)
        self.setPen(pen)

        self._label = QGraphicsSimpleTextItem(self)
        self._label.setText(rel_text)
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        self._label.setFont(font)
        self._label.setBrush(QBrush(QColor("#0f172a")))

        self.update_positions()

    def update_positions(self) -> None:
        """Recompute line end points and percentage label position when nodes move."""
        if not self.source_node or not self.target_node:
            return
        sp = self.source_node.scenePos()
        tp = self.target_node.scenePos()
        self.setLine(sp.x(), sp.y(), tp.x(), tp.y())

        mid = QPointF((sp.x() + tp.x()) / 2, (sp.y() + tp.y()) / 2)
        self._label.setPos(
            mid.x() - self._label.boundingRect().width() / 2,
            mid.y() - self._label.boundingRect().height() / 2,
        )

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(-50, -40, 50, 40)


class GraphView(QGraphicsView):
    """Interactive canvas rendering file entities and relationship edges with zoom & drag."""

    def __init__(
        self,
        on_entity_selected: Optional[Callable[[dict], None]] = None,
        on_evidence_activated: Optional[Callable[[dict], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._on_entity_selected = on_entity_selected
        self._on_evidence_activated = on_evidence_activated
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(QColor("#f8fafc")))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

        self._node_items: Dict[int, GraphNodeItem] = {}
        self._edge_items: List[GraphEdgeItem] = []

    # ------------------------------------------------------------------ #
    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Smooth mouse wheel zoom in / out centered on cursor."""
        zoom_factor = 1.18 if event.angleDelta().y() > 0 else 1.0 / 1.18
        self.scale(zoom_factor, zoom_factor)

    # ------------------------------------------------------------------ #
    def set_graph(
        self,
        entities: List[dict],
        relationships: List[dict],
        highlight_entity_id: Optional[int] = None,
    ) -> None:
        """Render graph using force-directed layout for spacious, organic node placement."""
        self._scene.clear()
        self._node_items.clear()
        self._edge_items.clear()

        if not entities:
            self._scene.addSimpleText("No files found in directory.")
            return

        # 1. Compute force-directed / spacious layout positions
        positions = self._compute_force_directed_layout(entities, relationships)

        # 2. Add Node Items
        for ent in entities:
            item = GraphNodeItem(ent)
            item.setPos(positions[ent["id"]])
            if highlight_entity_id is not None and ent["id"] == highlight_entity_id:
                item.setPen(QPen(QColor("#f59e0b"), 3.5))
            self._scene.addItem(item)
            self._node_items[ent["id"]] = item

        # 3. Add Edge Items (Clean percentage lines)
        # Limit visible edges to top 4 strongest per node to avoid visual clutter
        connected_edges = set()
        for rel in relationships:
            src_id = rel.get("source_id")
            tgt_id = rel.get("target_id")
            src_node = self._node_items.get(src_id)
            tgt_node = self._node_items.get(tgt_id)
            if src_node and tgt_node:
                edge_key = tuple(sorted((src_id, tgt_id)))
                if edge_key not in connected_edges:
                    edge = GraphEdgeItem(src_node, tgt_node, rel)
                    self._scene.addItem(edge)
                    self._edge_items.append(edge)
                    connected_edges.add(edge_key)

        self._scene.setSceneRect(self._scene.itemsBoundingRect().adjusted(-100, -100, 100, 100))
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    # ------------------------------------------------------------------ #
    def _compute_force_directed_layout(
        self, entities: List[dict], relationships: List[dict]
    ) -> Dict[int, QPointF]:
        """Spring / Force-directed layout algorithm for spacious, organic node distribution."""
        n = len(entities)
        positions: Dict[int, QPointF] = {}

        if n == 0:
            return positions

        # Separate connected nodes from disconnected nodes
        connected_ids = set()
        for r in relationships:
            connected_ids.add(r.get("source_id"))
            connected_ids.add(r.get("target_id"))

        connected_ents = [e for e in entities if e["id"] in connected_ids]
        disconnected_ents = [e for e in entities if e["id"] not in connected_ids]

        # Initial circular spread for connected nodes
        num_conn = len(connected_ents)
        for i, ent in enumerate(connected_ents):
            angle = 2 * math.pi * i / max(num_conn, 1)
            radius = 220 + (i % 5) * 20
            positions[ent["id"]] = QPointF(radius * math.cos(angle), radius * math.sin(angle))

        # Run 50 iterations of Force-Directed (Fruchterman-Reingold) simulation
        k = 180.0  # Ideal distance between nodes
        for _ in range(50):
            disp: Dict[int, QPointF] = {ent["id"]: QPointF(0, 0) for ent in connected_ents}

            # Repulsive force between node pairs
            for i in range(num_conn):
                e1 = connected_ents[i]["id"]
                p1 = positions[e1]
                for j in range(i + 1, num_conn):
                    e2 = connected_ents[j]["id"]
                    p2 = positions[e2]
                    dx = p1.x() - p2.x()
                    dy = p1.y() - p2.y()
                    dist = math.hypot(dx, dy) or 0.1
                    force = (k * k) / dist
                    disp[e1] = QPointF(disp[e1].x() + (dx / dist) * force, disp[e1].y() + (dy / dist) * force)
                    disp[e2] = QPointF(disp[e2].x() - (dx / dist) * force, disp[e2].y() - (dy / dist) * force)

            # Attractive force along relationship edges
            for rel in relationships:
                e1 = rel.get("source_id")
                e2 = rel.get("target_id")
                if e1 in positions and e2 in positions:
                    p1 = positions[e1]
                    p2 = positions[e2]
                    dx = p1.x() - p2.x()
                    dy = p1.y() - p2.y()
                    dist = math.hypot(dx, dy) or 0.1
                    force = (dist * dist) / k
                    disp[e1] = QPointF(disp[e1].x() - (dx / dist) * force, disp[e1].y() - (dy / dist) * force)
                    disp[e2] = QPointF(disp[e2].x() + (dx / dist) * force, disp[e2].y() + (dy / dist) * force)

            # Update positions with damping
            for ent in connected_ents:
                eid = ent["id"]
                d = disp[eid]
                d_len = math.hypot(d.x(), d.y()) or 0.1
                step = min(d_len, 25.0)
                positions[eid] = QPointF(
                    positions[eid].x() + (d.x() / d_len) * step,
                    positions[eid].y() + (d.y() / d_len) * step,
                )

        # Place disconnected nodes neatly in a perimeter grid at the bottom
        grid_x = -350
        grid_y = 400
        for i, ent in enumerate(disconnected_ents):
            col = i % 8
            row = i // 8
            positions[ent["id"]] = QPointF(grid_x + col * 100, grid_y + row * 90)

        return positions

    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, GraphNodeItem):
            self._on_entity_selected and self._on_entity_selected(item.entity)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, GraphNodeItem):
            if self._on_entity_selected:
                self._on_entity_selected(item.entity)
        super().mouseDoubleClickEvent(event)
