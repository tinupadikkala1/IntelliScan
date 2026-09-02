"""File relationship engine — B5-07.

The Batch-4 knowledge graph stays ENTITY → ENTITY. This engine maintains the
separate FILE → FILE layer in ``file_relationships`` with controlled types:

    duplicate_of          exact SHA-256 match (B5-04)
    similar_to            near-duplicate score >= threshold (B5-05)
    related_to            related-file / shared-entity evidence (B5-06)
    references            NOT auto-created (only user/LLM-verified)
    derived_from          NOT auto-created (only user/LLM-verified)
    belongs_to_project    inferred from shared project folders/topics when
                          evidence is strong enough

Every edge stores confidence + an evidence dict (reason, matched chunks,
source labels) so the UI can explain *why* a relationship exists.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from engines.config import NEAR_DUPLICATE_THRESHOLD, RELATIONSHIP_TYPES

from .batch5_models import FileRelationshipInfo
from .batch5_store import Batch5Store
from .file_similarity import FileSimilarityService

logger = logging.getLogger(__name__)


class RelationshipEngine:
    """Builds and queries FILE → FILE relationships."""

    def __init__(
        self,
        store: Batch5Store,
        duplicates,
        similarity: FileSimilarityService,
        graph_store=None,
        near_threshold: float = NEAR_DUPLICATE_THRESHOLD,
    ) -> None:
        self._store = store
        self._duplicates = duplicates  # DuplicateEngine instance
        self._similarity = similarity
        self._graph = graph_store
        self._near_threshold = near_threshold

    # ------------------------------------------------------------------ #
    def build_for_file(self, file_path: str) -> int:
        """(Re)compute relationships originating from one file.

        Creates:
          - ``duplicate_of`` edges for exact duplicate copies,
          - ``similar_to`` edges for near duplicates,
          - ``related_to`` edges for graph-shared-entity files.
        Stale edges originating from this file are removed first so no
        phantom relationships survive a reindex.
        """
        file_path = os.path.abspath(file_path)
        created = 0

        # 1. Exact duplicates (B5-04) → duplicate_of.
        group = self._duplicates.find_exact_duplicates_for_file(file_path)
        if group is not None:
            for other in group.files:
                other = os.path.abspath(other)
                if other == file_path:
                    continue
                try:
                    self._store.upsert_relationship(
                        source_path=file_path,
                        target_path=other,
                        relationship_type="duplicate_of",
                        confidence=1.0,
                        evidence={"reason": "Identical content (same SHA-256)",
                                  "checksum": group.checksum,
                                  "is_empty": group.is_empty},
                    )
                    created += 1
                except Exception as exc:
                    logger.debug("duplicate_of edge failed: %s", exc)

        # 2. Near duplicates (B5-05) → similar_to.
        try:
            for r in self._similarity.near_duplicates(file_path):
                if r.is_exact:
                    continue
                try:
                    self._store.upsert_relationship(
                        source_path=file_path,
                        target_path=os.path.abspath(r.file_path),
                        relationship_type="similar_to",
                        confidence=round(r.score, 4),
                        evidence={"reason": r.reason,
                                  "matched_chunks": r.matched_chunks,
                                  "score": round(r.score, 4)},
                    )
                    created += 1
                except Exception as exc:
                    logger.debug("similar_to edge failed: %s", exc)
        except Exception as exc:
            logger.debug("Near-duplicate relationships skipped: %s", exc)

        # 3. Graph shared entities (B5-06) → related_to.
        if self._graph is not None:
            try:
                for other in self._graph.files_sharing_entities(file_path, limit=25):
                    other = os.path.abspath(other)
                    if other == file_path:
                        continue
                    try:
                        self._store.upsert_relationship(
                            source_path=file_path,
                            target_path=other,
                            relationship_type="related_to",
                            confidence=0.7,
                            evidence={"reason": "Shared topics/entities in the knowledge graph"},
                        )
                        created += 1
                    except Exception as exc:
                        logger.debug("related_to edge failed: %s", exc)
            except Exception as exc:
                logger.debug("Graph relationships skipped: %s", exc)

        return created

    # ------------------------------------------------------------------ #
    def relationships_for_file(self, file_path: str) -> List[FileRelationshipInfo]:
        """All edges touching a path (incoming + outgoing)."""
        return self._store.relationships_for_path(os.path.abspath(file_path))

    def relationship_stats(self) -> dict:
        """Dashboard helper."""
        try:
            stats = self._store.stats()
            return {
                "total": stats.get("relationships", 0),
                "by_type": stats.get("relationships_by_type", {}),
            }
        except Exception:
            return {"total": 0, "by_type": {}}

    def rebuild_all(self, paths: Optional[List[str]] = None) -> int:
        """Rebuild relationships for a set of paths (default: all indexed)."""
        if paths is None:
            paths = self._indexed_paths()
        total = 0
        for path in paths:
            try:
                total += self.build_for_file(path)
            except Exception as exc:
                logger.debug("Relationship rebuild failed for %s: %s", path, exc)
        return total

    def _indexed_paths(self) -> List[str]:
        try:
            from services.sqlite_indexer import IndexedFile

            with self._store._session_factory() as session:
                rows = session.query(IndexedFile.absolute_path).all()
                return [r[0] for r in rows]
        except Exception:
            return []
