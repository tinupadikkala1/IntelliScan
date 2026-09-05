"""Knowledge dashboard service — B5-10.

Aggregates statistics across the existing indexing, AI, retrieval, graph and
organization infrastructure. Composes existing queries rather than adding new
dashboard tables. Never scans the unbounded ``tasks`` table (Batch 5 §21 rule
9). All counts are derived live so a stale file never appears twice.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class DashboardService:
    """Read-side aggregation for the Knowledge Dashboard."""

    def __init__(
        self,
        session_factory,
        duplicates=None,
        relationship_engine=None,
        collection_engine=None,
        classifier=None,
        tagger=None,
        graph_store=None,
        db_store=None,
        retrieval=None,
    ) -> None:
        self._session_factory = session_factory
        self._duplicates = duplicates
        self._relationships = relationship_engine
        self._collections = collection_engine
        self._classifier = classifier
        self._tagger = tagger
        self._graph = graph_store
        self._db_store = db_store
        self._retrieval = retrieval

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    def snapshot(self, folder_path: Optional[str] = None) -> dict:
        """Full dashboard snapshot (all sections)."""
        return {
            "files": self.files_stats(folder_path=folder_path),
            "ai": self.ai_stats(folder_path=folder_path),
            "semantic": self.semantic_stats(),
            "duplicates": self.duplicate_stats(folder_path=folder_path),
            "relationships": self.relationship_stats(),
            "collections": self.collection_stats(),
            "graph": self.graph_stats(),
            "system": self.system_stats(),
            "recent": self.recent_files(limit=8, folder_path=folder_path),
        }

    def refresh(self, folder_path: Optional[str] = None) -> dict:
        """Backend refresh logic: syncs latest data from engines/db and returns an updated snapshot."""
        logger.info("Refreshing knowledge dashboard stats (scope: %s)", folder_path or "workspace")
        if self._retrieval is not None and hasattr(self._retrieval, "hydrate_from_store"):
            try:
                self._retrieval.hydrate_from_store()
            except Exception as e:
                logger.debug("Retrieval hydration during dashboard refresh: %s", e)

        return self.snapshot(folder_path=folder_path)

    # ------------------------------------------------------------------ #
    def files_stats(self, folder_path: Optional[str] = None) -> dict:
        try:
            import os
            from services.sqlite_indexer import IndexedFile

            with self._session_factory() as session:
                rows = session.query(
                    IndexedFile.absolute_path, IndexedFile.extension, IndexedFile.mime_type
                ).all()

                if folder_path:
                    abs_folder = os.path.abspath(folder_path).rstrip(os.sep)
                    norm_folder = abs_folder + os.sep
                    rows = [
                        r for r in rows
                        if r[0] and (os.path.abspath(r[0]) == abs_folder or os.path.abspath(r[0]).startswith(norm_folder))
                    ]

                total = len(rows)
                by_ext = {}
                by_type = {}
                for p, ext, mime in rows:
                    e = (ext or "").lower()
                    by_ext[e] = by_ext.get(e, 0) + 1
                    m = (mime or "unknown").split("/")[0]
                    by_type[m] = by_type.get(m, 0) + 1
            return {
                "total": total,
                "by_extension": by_ext,
                "by_type": by_type,
            }
        except Exception as exc:
            logger.debug("files stats failed: %s", exc)
            return {"total": 0, "by_extension": {}, "by_type": {}}

    def recent_files(self, limit: int = 8, folder_path: Optional[str] = None) -> list:
        try:
            import os
            from services.sqlite_indexer import IndexedFile

            with self._session_factory() as session:
                rows = (
                    session.query(IndexedFile.filename, IndexedFile.absolute_path,
                                 IndexedFile.modified_date)
                    .order_by(IndexedFile.modified_date.desc())
                    .all()
                )
                if folder_path:
                    abs_folder = os.path.abspath(folder_path).rstrip(os.sep)
                    norm_folder = abs_folder + os.sep
                    rows = [
                        r for r in rows
                        if r[1] and (os.path.abspath(r[1]) == abs_folder or os.path.abspath(r[1]).startswith(norm_folder))
                    ]
                return [
                    {"filename": r[0], "path": r[1],
                     "modified": str(r[2])[:16] if r[2] else ""}
                    for r in rows[:limit]
                ]
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    def ai_stats(self, folder_path: Optional[str] = None) -> dict:
        try:
            import os
            from database.models import AIAnalysis
            from services.sqlite_indexer import IndexedFile

            with self._session_factory() as session:
                idx_rows = session.query(IndexedFile.absolute_path, IndexedFile.checksum).all()
                if folder_path:
                    abs_folder = os.path.abspath(folder_path).rstrip(os.sep)
                    norm_folder = abs_folder + os.sep
                    idx_rows = [
                        r for r in idx_rows
                        if r[0] and (os.path.abspath(r[0]) == abs_folder or os.path.abspath(r[0]).startswith(norm_folder))
                    ]
                indexed_hashes = {r[1] for r in idx_rows if r[1]}
                analyzed = 0
                categories = {}
                for row in session.query(AIAnalysis).all():
                    if row.file_hash not in indexed_hashes:
                        continue
                    if row.summary or row.category or row.normalized_category:
                        analyzed += 1
                    cat = row.normalized_category or row.category
                    if cat:
                        categories[cat] = categories.get(cat, 0) + 1
                return {
                    "analyzed": analyzed,
                    "unanalyzed": max(0, len(indexed_hashes) - analyzed),
                    "total_indexed": len(indexed_hashes),
                    "categories": categories,
                }
        except Exception as exc:
            logger.debug("ai stats failed: %s", exc)
            return {"analyzed": 0, "unanalyzed": 0, "total_indexed": 0, "categories": {}}

    def semantic_stats(self) -> dict:
        try:
            evidence = 0
            vector_map = 0
            recent_searches = 0
            if self._db_store is not None:
                evidence = len(self._db_store.get_all_evidence())
                vector_map = len(self._db_store.get_all_vector_maps())
                recent_searches = len(self._db_store.get_recent_searches(limit=1000))
            indexed_files = 0
            if self._retrieval is not None:
                try:
                    indexed_files = self._retrieval.indexed_count
                except Exception:
                    indexed_files = 0
                if evidence == 0 and hasattr(self._retrieval, "_evidence") and self._retrieval._evidence:
                    evidence = len(self._retrieval._evidence)
                if vector_map == 0 and hasattr(self._retrieval, "_vector") and hasattr(self._retrieval._vector, "size"):
                    vector_map = self._retrieval._vector.size
            return {
                "ai_indexed_files": indexed_files,
                "evidence_chunks": evidence,
                "vectors": vector_map,
                "recent_searches": recent_searches,
            }
        except Exception as exc:
            logger.debug("semantic stats failed: %s", exc)
            return {"ai_indexed_files": 0, "evidence_chunks": 0, "vectors": 0,
                    "recent_searches": 0}

    def duplicate_stats(self, folder_path: Optional[str] = None) -> dict:
        if self._duplicates is None:
            return {"groups": 0, "duplicate_files": 0, "extra_copies_bytes": 0}
        try:
            groups = self._duplicates.find_exact_duplicates(folder_path=folder_path)
            dup_files = sum(len(g.files) - 1 for g in groups)
            wasted = sum(
                (len(g.files) - 1) * (g.total_size // len(g.files)) if g.files else 0
                for g in groups
            )
            return {
                "groups": len(groups),
                "duplicate_files": dup_files,
                "extra_copies_bytes": wasted,
                "empty_groups": sum(1 for g in groups if g.is_empty),
            }
        except Exception:
            return {"groups": 0, "duplicate_files": 0, "extra_copies_bytes": 0}

    def relationship_stats(self) -> dict:
        if self._relationships is None:
            return {"total": 0, "by_type": {}}
        try:
            return self._relationships.relationship_stats()
        except Exception:
            return {"total": 0, "by_type": {}}

    def collection_stats(self) -> dict:
        if self._collections is None:
            return {"total": 0, "static": 0, "smart": 0, "members": 0}
        try:
            stats = self._collections._store.stats()
            return {
                "total": stats.get("collections", 0),
                "static": max(0, stats.get("collections", 0) - stats.get("smart_collections", 0)),
                "smart": stats.get("smart_collections", 0),
                "members": stats.get("collection_items", 0),
            }
        except Exception:
            return {"total": 0, "static": 0, "smart": 0, "members": 0}

    def graph_stats(self) -> dict:
        if self._graph is None:
            return {"entities": 0, "relationships": 0, "evidence_links": 0}
        try:
            return self._graph.stats()
        except Exception:
            return {"entities": 0, "relationships": 0, "evidence_links": 0}

    def system_stats(self) -> dict:
        """Indexing state, AI availability, watcher status (best effort)."""
        try:
            from services.sqlite_indexer import IndexedFile

            with self._session_factory() as session:
                pending = (
                    session.query(IndexedFile)
                    .filter(IndexedFile.indexing_status == "pending")
                    .count()
                )
                failed = (
                    session.query(IndexedFile)
                    .filter(IndexedFile.indexing_status == "failed")
                    .count()
                )
        except Exception:
            pending = failed = 0

        ai_available = False
        try:
            if self._retrieval is not None:
                ai_available = self._retrieval.indexed_count > 0
        except Exception:
            ai_available = False

        return {
            "indexing_pending": pending,
            "indexing_failed": failed,
            "ai_index_available": ai_available,
        }
