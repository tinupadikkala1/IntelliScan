"""Database store for Batch 3 engines.

Provides persistence for evidence chunks, vector mappings, and search
history. Works with the shared SQLAlchemy Base from database.models.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import List, Optional, Set

from database.models import Evidence, SearchHistory, VectorMap

from .evidence_engine import EvidenceChunk

logger = logging.getLogger(__name__)


def _with_retry(fn, what: str = "db write", tries: int = 3):
    """Retry on 'database is locked' with jitter (QThreadPool-safe)."""
    import random
    import time

    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:
            last = e
            msg = str(e).lower()
            if "locked" in msg or "busy" in msg:
                time.sleep(0.05 * attempt + random.random() * 0.05)
                continue
            raise
    assert last is not None
    raise last


class PersistenceError(Exception):
    """Raised when a database write cannot be completed.

    Batch 4 M0-06: persistence failures must be visible to callers instead
    of silently degrading into "apparently successful" operations. Callers
    (indexing, conversation persistence) surface this to the UI/logger.
    """


class EngineDBStore:
    """Persistence layer for the retrieval engine.

    Stores evidence chunks and vector mappings in SQLite so that
    the FAISS index can be rebuilt on application restart.
    """

    def __init__(self, session_factory) -> None:
        """Initialize with a SQLAlchemy session factory.

        Args:
            session_factory: Callable returning a new session.
        """
        self._session_factory = session_factory

    # ================================================================
    # Evidence CRUD
    # ================================================================

    def store_evidence(self, chunks: List[EvidenceChunk]) -> int:
        """Store evidence chunks in SQLite.

        Args:
            chunks: List of EvidenceChunk objects to persist.

        Returns:
            Number of chunks stored successfully.

        Raises:
            PersistenceError: if the database write fails.
        """
        logger.info("Storing %d evidence chunks", len(chunks))
        stored = 0
        try:
            with self._session_factory() as session:
                for chunk in chunks:
                    existing = session.query(Evidence).filter_by(
                        chunk_id=chunk.chunk_id
                    ).first()
                    if existing:
                        continue  # Skip duplicates

                    record = Evidence(
                        chunk_id=chunk.chunk_id,
                        file_path=chunk.file_path,
                        file_hash=chunk.file_hash,
                        text=chunk.text,
                        source_type=chunk.source_type,
                        source_index=chunk.source_index,
                        source_label=chunk.source_label,
                        char_start=chunk.char_start,
                        char_end=chunk.char_end,
                        modality=getattr(chunk, "modality", "document"),
                        timestamp_start=getattr(chunk, "timestamp_start", 0.0) or 0.0,
                        timestamp_end=getattr(chunk, "timestamp_end", 0.0) or 0.0,
                        confidence=getattr(chunk, "confidence", 1.0) or 1.0,
                        metadata_json=json.dumps(chunk.metadata or {}),
                        indexed_at=datetime.now(),
                    )
                    session.add(record)
                    stored += 1
                session.commit()
            logger.info("Stored %d evidence chunks", stored)
        except Exception as e:
            logger.error("Failed to store evidence: %s", e)
            raise PersistenceError(f"Could not persist {len(chunks)} evidence chunks: {e}") from e
        return stored

    def get_evidence_by_file(self, file_path: str) -> List[EvidenceChunk]:
        """Load all evidence chunks for a file (path-normalized)."""
        try:
            from services.path_utils import norm as _norm

            _cands = {file_path, _norm(file_path)}
            try:
                _cands.add(os.path.realpath(file_path))
            except Exception:
                pass
            with self._session_factory() as session:
                records = session.query(Evidence).filter(Evidence.file_path.in_(list(_cands))).all()
                # Fallback scan for case-junction variants (small tables only)
                if not records:
                    try:
                        _t = _norm(file_path)
                        _all = session.query(Evidence).all()
                        records = [r for r in _all if _norm(getattr(r, "file_path", "")) == _t]
                    except Exception:
                        records = []
                return [self._record_to_chunk(r) for r in records]
        except Exception as e:
            logger.error("Failed to load evidence for %s: %s", file_path, e)
            return []

    def get_all_evidence(self) -> List[EvidenceChunk]:
        """Load all evidence chunks from the database.

        Returns:
            List of all EvidenceChunk objects.
        """
        try:
            with self._session_factory() as session:
                records = session.query(Evidence).all()
                return [self._record_to_chunk(r) for r in records]
        except Exception as e:
            logger.error("Failed to load all evidence: %s", e)
            return []

    def delete_evidence_by_file(self, file_path: str) -> int:
        """Delete all evidence for a file.

        Args:
            file_path: Absolute path of the file.

        Returns:
            Number of records deleted.

        Raises:
            PersistenceError: if the database write fails.
        """
        try:
            with self._session_factory() as session:
                count = session.query(Evidence).filter_by(
                    file_path=file_path
                ).delete()
                session.query(VectorMap).filter_by(
                    file_path=file_path
                ).delete()
                session.commit()
                logger.info("Deleted %d evidence records for %s", count, file_path)
                return count
        except Exception as e:
            logger.error("Failed to delete evidence for %s: %s", file_path, e)
            raise PersistenceError(f"Could not delete evidence for {file_path}: {e}") from e

    def update_file_hash(self, file_path: str, new_hash: str) -> None:
        """Update file_hash for all evidence chunks and vector maps of a file."""
        if not new_hash:
            return
        try:
            with self._session_factory() as session:
                session.query(Evidence).filter_by(file_path=file_path).update({"file_hash": new_hash})
                session.query(VectorMap).filter_by(file_path=file_path).update({"file_hash": new_hash})
                session.commit()
        except Exception as e:
            logger.debug("Failed to update file hash for %s: %s", file_path, e)

    def get_evidence_by_hash(self, file_hash: str) -> List[EvidenceChunk]:
        """Return all evidence chunks whose file_hash matches the given hash.

        Used for rename detection: if a 'new' file's hash already exists in the
        DB under a different path, the file was renamed rather than added fresh.

        Args:
            file_hash: SHA-256 hex digest to look up.

        Returns:
            List of EvidenceChunk objects (may be from multiple files if there
            are exact duplicates, though normally just one file).
        """
        if not file_hash:
            return []
        try:
            with self._session_factory() as session:
                records = session.query(Evidence).filter_by(file_hash=file_hash).all()
                return [self._record_to_chunk(r) for r in records]
        except Exception as e:
            logger.debug("get_evidence_by_hash failed for hash %s: %s", file_hash[:8], e)
            return []

    def update_file_path(self, old_path: str, new_path: str, new_filename: str = "") -> int:
        """Atomically rename a file's path across evidence and vector_map tables.

        Called when a rename is detected (hash match under a different path).
        Updates every evidence chunk and vector map row that references old_path
        to use new_path instead.

        Args:
            old_path: The previously stored absolute path.
            new_path: The new absolute path after rename.
            new_filename: Optional filename override (derived from new_path if omitted).

        Returns:
            Number of evidence rows updated.
        """
        if not old_path or not new_path or old_path == new_path:
            return 0
        try:
            with self._session_factory() as session:
                ev_count = session.query(Evidence).filter_by(file_path=old_path).update(
                    {"file_path": new_path}, synchronize_session=False
                )
                session.query(VectorMap).filter_by(file_path=old_path).update(
                    {"file_path": new_path}, synchronize_session=False
                )
                session.commit()
            logger.info(
                "Rename detected: updated %d evidence rows from '%s' → '%s'",
                ev_count, os.path.basename(old_path), os.path.basename(new_path),
            )
            return ev_count
        except Exception as e:
            logger.error("Failed to update file path %s → %s: %s", old_path, new_path, e)
            return 0

    def delete_evidence_by_chunk_ids(self, chunk_ids: Set[str] | List[str]) -> int:
        """Delete evidence records and vector maps matching chunk IDs."""
        if not chunk_ids:
            return 0
        cids = list(chunk_ids)
        try:
            with self._session_factory() as session:
                count = session.query(Evidence).filter(
                    Evidence.chunk_id.in_(cids)
                ).delete(synchronize_session=False)
                session.query(VectorMap).filter(
                    VectorMap.chunk_id.in_(cids)
                ).delete(synchronize_session=False)
                session.commit()
                logger.info("Deleted %d evidence records by chunk IDs", count)
                return count
        except Exception as e:
            logger.debug("Failed to delete evidence by chunk IDs: %s", e)
            return 0

    def get_indexed_file_hashes(self) -> Set[str]:
        """Get set of all file hashes that have been indexed.

        Returns:
            Set of file_hash strings.
        """
        try:
            with self._session_factory() as session:
                rows = session.query(Evidence.file_hash).distinct().all()
                return {r[0] for r in rows}
        except Exception as e:
            logger.error("Failed to get indexed hashes: %s", e)
            return set()

    # ================================================================
    # Vector Map
    # ================================================================

    def store_vector_map(self, chunk_id: str, file_path: str, file_hash: str, model: str) -> bool:
        """Record that a chunk has been embedded and indexed.

        Args:
            chunk_id: Unique chunk identifier.
            file_path: Source file path.
            file_hash: SHA-256 of the source file.
            model: Embedding model name used.

        Returns:
            True if stored successfully.

        Raises:
            PersistenceError: if the database write fails.
        """
        try:
            with self._session_factory() as session:
                existing = session.query(VectorMap).filter_by(chunk_id=chunk_id).first()
                if not existing:
                    session.add(VectorMap(
                        chunk_id=chunk_id,
                        file_path=file_path,
                        file_hash=file_hash,
                        embedding_model=model,
                        indexed_at=datetime.now(),
                    ))
                    session.commit()
            return True
        except Exception as e:
            logger.error("Failed to store vector map for %s: %s", chunk_id[:8], e)
            raise PersistenceError(f"Could not persist vector map for {chunk_id[:8]}: {e}") from e

    def store_vector_maps(self, chunk_ids: List[str], file_path: str, file_hash: str, model: str) -> int:
        """Record that a batch of chunks has been embedded and indexed.

        Args:
            chunk_ids: List of chunk identifiers.
            file_path: Source file path.
            file_hash: SHA-256 of the source file.
            model: Embedding model name used.

        Returns:
            Number of vector-map rows stored.

        Raises:
            PersistenceError: if the database write fails.
        """
        if not chunk_ids:
            return 0
        stored = 0
        try:
            with self._session_factory() as session:
                existing = {
                    row[0] for row in session.query(VectorMap.chunk_id).filter(
                        VectorMap.chunk_id.in_(chunk_ids)
                    ).all()
                }
                for cid in chunk_ids:
                    if cid in existing:
                        continue
                    session.add(VectorMap(
                        chunk_id=cid,
                        file_path=file_path,
                        file_hash=file_hash,
                        embedding_model=model,
                        indexed_at=datetime.now(),
                    ))
                    stored += 1
                session.commit()
            return stored
        except Exception as e:
            logger.error("Failed to store vector maps batch: %s", e)
            raise PersistenceError(f"Could not persist {len(chunk_ids)} vector maps: {e}") from e

    def get_all_vector_maps(self) -> List[dict]:
        """Load all vector mappings from the database.

        Returns:
            List of dicts with chunk_id, file_path, file_hash, embedding_model.
        """
        try:
            with self._session_factory() as session:
                records = session.query(VectorMap).all()
                return [
                    {
                        "chunk_id": r.chunk_id,
                        "file_path": r.file_path,
                        "file_hash": r.file_hash,
                        "embedding_model": r.embedding_model,
                    }
                    for r in records
                ]
        except Exception as e:
            logger.error("Failed to load vector maps: %s", e)
            return []

    def get_vector_maps_by_file(self, file_path: str) -> List[dict]:
        """Load vector mappings for a single file.

        Returns:
            List of dicts with chunk_id, file_path, file_hash, embedding_model.
        """
        try:
            with self._session_factory() as session:
                records = session.query(VectorMap).filter_by(file_path=file_path).all()
                return [
                    {
                        "chunk_id": r.chunk_id,
                        "file_path": r.file_path,
                        "file_hash": r.file_hash,
                        "embedding_model": r.embedding_model,
                    }
                    for r in records
                ]
        except Exception as e:
            logger.error("Failed to load vector maps for %s: %s", file_path, e)
            return []

    def has_evidence_for_file(self, file_path: str) -> bool:
        """Return True if any evidence rows exist for a file."""
        try:
            with self._session_factory() as session:
                return session.query(Evidence).filter_by(file_path=file_path).count() > 0
        except Exception as e:
            logger.error("Failed to check evidence for %s: %s", file_path, e)
            return False

    # ================================================================
    # Search History
    # ================================================================

    def record_search(self, query: str, scope: str, results_count: int, elapsed_ms: int) -> None:
        """Record a search query in history.

        Args:
            query: The search query text.
            scope: Search scope used.
            results_count: Number of results returned.
            elapsed_ms: Time taken in milliseconds.

        Raises:
            PersistenceError: if the database write fails.
        """
        try:
            with self._session_factory() as session:
                session.add(SearchHistory(
                    query=query,
                    scope=scope,
                    results_count=results_count,
                    elapsed_ms=elapsed_ms,
                    searched_at=datetime.now(),
                ))
                session.commit()
        except Exception as e:
            logger.error("Failed to record search: %s", e)
            raise PersistenceError(f"Could not record search history: {e}") from e

    def get_recent_searches(self, limit: int = 20) -> List[dict]:
        """Get recent search history.

        Args:
            limit: Maximum number of recent searches to return.

        Returns:
            List of search history dicts.
        """
        try:
            with self._session_factory() as session:
                records = session.query(SearchHistory).order_by(
                    SearchHistory.searched_at.desc()
                ).limit(limit).all()
                return [
                    {
                        "query": r.query,
                        "scope": r.scope,
                        "results_count": r.results_count,
                        "elapsed_ms": r.elapsed_ms,
                        "searched_at": r.searched_at,
                    }
                    for r in records
                ]
        except Exception as e:
            logger.error("Failed to get search history: %s", e)
            return []

    # ================================================================
    # Helpers
    # ================================================================

    @staticmethod
    def _record_to_chunk(record: Evidence) -> EvidenceChunk:
        """Convert a DB Evidence record to an EvidenceChunk."""
        metadata = {}
        if getattr(record, "metadata_json", None):
            try:
                metadata = json.loads(record.metadata_json) or {}
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        return EvidenceChunk(
            chunk_id=record.chunk_id,
            text=record.text,
            file_path=record.file_path,
            file_hash=record.file_hash,
            source_type=record.source_type or "",
            source_index=record.source_index or 0,
            source_label=record.source_label or "",
            char_start=record.char_start or 0,
            char_end=record.char_end or 0,
            modality=getattr(record, "modality", None) or "document",
            timestamp_start=getattr(record, "timestamp_start", 0.0) or 0.0,
            timestamp_end=getattr(record, "timestamp_end", 0.0) or 0.0,
            confidence=getattr(record, "confidence", 1.0) or 1.0,
            metadata=metadata,
        )
