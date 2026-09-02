"""Graph engine — orchestrates entity/relationship extraction and persistence.

Wired into AIFolderIndexer: after a file is indexed, ``index_file`` extracts
entities + relationships from a bounded sample of its evidence chunks and
stores them with full provenance. ``remove_file`` cleans up after deletes.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from engines.config import (
    GRAPH_EXTRACTION_ENABLED,
    GRAPH_MAX_CHUNKS_PER_FILE,
)

from .entity_extractor import EntityExtractor
from .graph_models import EntityRecord
from .graph_store import GraphStore
from .relationship_extractor import RelationshipExtractor

logger = logging.getLogger(__name__)


class GraphEngine:
    """High-level knowledge graph service used by indexing and the UI."""

    def __init__(
        self,
        session_factory,
        rag=None,
        resources=None,
        store: Optional[GraphStore] = None,
        enabled: bool = GRAPH_EXTRACTION_ENABLED,
        max_chunks_per_file: int = GRAPH_MAX_CHUNKS_PER_FILE,
    ) -> None:
        self._store = store or GraphStore(session_factory)
        self._enabled = enabled
        self._max_chunks = max_chunks_per_file
        self._entity_extractor = EntityExtractor(rag, resources) if rag is not None else None
        self._relationship_extractor = RelationshipExtractor(rag, resources) if rag is not None else None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    @property
    def store(self) -> GraphStore:
        return self._store

    # ------------------------------------------------------------------ #
    def index_file(self, file_path: str, chunks) -> dict:
        """Extract + persist graph data for one indexed file.

        Args:
            file_path: Source file.
            chunks: EvidenceChunk list for the file (already indexed).

        Returns:
            {"entities": n, "relationships": n, "error": str|None}
        """
        if not self._enabled or self._entity_extractor is None:
            return {"entities": 0, "relationships": 0, "error": "disabled"}
        try:
            sample = chunks[: self._max_chunks]
            entity_ids: Dict[str, int] = {}

            # 1. Entities from every sampled chunk.
            for chunk in sample:
                text = getattr(chunk, "text", "") or ""
                records = self._entity_extractor.extract(text)
                for rec in records:
                    try:
                        eid = self._store.upsert_entity(rec)
                        entity_ids[rec.normalized_name] = eid
                    except Exception as exc:
                        logger.debug("Entity upsert failed: %s", exc)

            # 2. Relationships within each chunk, against the file's entities.
            rel_count = 0
            for chunk in sample:
                if not entity_ids:
                    break
                text = getattr(chunk, "text", "") or ""
                rels = self._relationship_extractor.extract(
                    text,
                    entity_ids,
                    chunk_id=getattr(chunk, "chunk_id", "") or "",
                    file_path=file_path,
                    source_label=getattr(chunk, "source_label", "") or "",
                    source_index=getattr(chunk, "source_index", 0) or 0,
                )
                for rel in rels:
                    try:
                        self._store.add_relationship(
                            rel,
                            entity_ids[rel.source_normalized],
                            entity_ids[rel.target_normalized],
                        )
                        rel_count += 1
                    except Exception as exc:
                        logger.debug("Relationship add failed: %s", exc)

            logger.info(
                "Graph: %d entities, %d relationships for %s",
                len(entity_ids), rel_count, file_path,
            )
            return {"entities": len(entity_ids), "relationships": rel_count, "error": None}
        except Exception as exc:
            logger.error("Graph indexing failed for %s: %s", file_path, exc)
            return {"entities": 0, "relationships": 0, "error": str(exc)}

    def remove_file(self, file_path: str) -> int:
        """Remove graph data derived from a file (Batch 4 §31)."""
        if self._store is None:
            return 0
        return self._store.remove_file(file_path)

    def stats(self) -> dict:
        return self._store.stats()
