"""Service-layer dataclasses for the knowledge graph."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from engines.config import GRAPH_ENTITY_TYPES

# Allowed entity types (controlled — Batch 4 §28).
ALLOWED_ENTITY_TYPES: set = set(GRAPH_ENTITY_TYPES)


def normalize_entity_name(name: str) -> str:
    """Normalize an entity name for duplicate detection.

    Batch 4 §30: case, whitespace and punctuation are folded so
    ``Python`` / ``python`` / ``PYTHON`` merge into one node. Uncontrolled
    fuzzy merging is deliberately NOT used.
    """
    if not name:
        return ""
    text = name.strip()
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s'&-]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass
class EntityRecord:
    name: str
    entity_type: str = "CONCEPT"
    aliases: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.entity_type = self._coerce_type(self.entity_type)

    @staticmethod
    def _coerce_type(entity_type: str) -> str:
        t = (entity_type or "CONCEPT").strip().upper()
        return t if t in ALLOWED_ENTITY_TYPES else "CONCEPT"

    @property
    def normalized_name(self) -> str:
        return normalize_entity_name(self.name)


@dataclass
class RelationshipRecord:
    source: str
    relation: str
    target: str
    confidence: float = 1.0
    chunk_id: str = ""
    file_path: str = ""
    source_label: str = ""
    source_index: int = 0

    @property
    def source_normalized(self) -> str:
        return normalize_entity_name(self.source)

    @property
    def target_normalized(self) -> str:
        return normalize_entity_name(self.target)


@dataclass
class EntityDetail:
    id: int
    name: str
    entity_type: str
    aliases: List[str]
    relationship_count: int
    related_files: List[str]
    relationships: List[dict]
