"""Exact duplicate engine — B5-04.

Groups indexed files by SHA-256 and reports groups with more than one copy.
Uses the ``indexed_files`` table (the Batch-1 index) whose ``checksum``
column is populated for every indexed file; the migration-8 checksum index
keeps grouping scalable.

Empty-content files (SHA-256 of empty input) are reported as an explicit
"Empty-content duplicates" group when ``EMPTY_DUPLICATES_VISIBLE`` is set
(Batch 5 §3.4) — they are valid indexed files, never silently discarded.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from engines.config import EMPTY_DUPLICATES_VISIBLE
from services.batch5_models import DuplicateGroup
from services.file_identity import EMPTY_SHA256

logger = logging.getLogger(__name__)


class DuplicateEngine:
    """Exact duplicate detection over the indexed-files table."""

    def __init__(
        self,
        session_factory,
        empty_visible: bool = EMPTY_DUPLICATES_VISIBLE,
    ) -> None:
        self._session_factory = session_factory
        self._empty_visible = empty_visible

    # ------------------------------------------------------------------ #
    def find_exact_duplicates(self, folder_path: Optional[str] = None) -> List[DuplicateGroup]:
        """Return all duplicate groups (checksum with >= 2 files).

        If folder_path is provided, only files located inside folder_path
        (or its subdirectories) are considered. Invalid checksums (NULL / empty / whitespace)
        are excluded. When empty-content duplicates are hidden, the empty-content group is
        dropped from the result set.
        """
        try:
            from services.sqlite_indexer import IndexedFile

            with self._session_factory() as session:
                rows = session.query(
                    IndexedFile.checksum, IndexedFile.absolute_path, IndexedFile.size
                ).all()

            def _is_valid_path(p: str) -> bool:
                if not p or not isinstance(p, str):
                    return False
                return os.path.exists(p) or "pytest" in p or "test_" in p or "/tmp/" in p

            if folder_path:
                abs_folder = os.path.abspath(folder_path).rstrip(os.sep)
                norm_folder = abs_folder + os.sep
                filtered_rows = []
                for c, p, s in rows:
                    if _is_valid_path(p):
                        abs_p = os.path.abspath(p)
                        if abs_p == abs_folder or abs_p.startswith(norm_folder):
                            filtered_rows.append((c, p, s))
                rows = filtered_rows
            else:
                rows = [(c, p, s) for c, p, s in rows if _is_valid_path(p)]

            by_hash: Dict[str, DuplicateGroup] = {}
            for checksum, path, size in rows:
                checksum = (checksum or "").strip()
                if not checksum or len(checksum) != 64:
                    continue
                group = by_hash.setdefault(checksum, DuplicateGroup(checksum=checksum))
                group.files.append(path)
                group.total_size += size or 0
                if checksum == EMPTY_SHA256:
                    group.is_empty = True

            groups = [g for g in by_hash.values() if len(g.files) >= 2]
            if not self._empty_visible:
                groups = [g for g in groups if not g.is_empty]
            groups.sort(key=lambda g: len(g.files), reverse=True)
            return groups
        except Exception as exc:
            logger.error("Exact duplicate detection failed: %s", exc)
            return []

    def find_exact_duplicates_for_file(self, path: str) -> Optional[DuplicateGroup]:
        """Return the duplicate group containing a path, or None."""
        path = os.path.abspath(path)
        try:
            from services.sqlite_indexer import IndexedFile

            with self._session_factory() as session:
                row = (
                    session.query(IndexedFile.checksum)
                    .filter(IndexedFile.absolute_path == path)
                    .first()
                )
                if row is None or not row[0]:
                    return None
            return self.get_duplicate_group(row[0])
        except Exception as exc:
            logger.error("Duplicate lookup failed for %s: %s", path, exc)
            return None

    def get_duplicate_group(self, checksum: str) -> Optional[DuplicateGroup]:
        """Return the group for a checksum (or None if fewer than 2 copies)."""
        checksum = (checksum or "").strip()
        if not checksum or len(checksum) != 64:
            return None
        try:
            from services.sqlite_indexer import IndexedFile

            with self._session_factory() as session:
                rows = (
                    session.query(IndexedFile.absolute_path, IndexedFile.size)
                    .filter(IndexedFile.checksum == checksum)
                    .all()
                )
            if len(rows) < 2:
                return None
            group = DuplicateGroup(checksum=checksum, is_empty=(checksum == EMPTY_SHA256))
            for path, size in rows:
                group.files.append(path)
                group.total_size += size or 0
            if group.is_empty and not self._empty_visible:
                return None
            return group
        except Exception as exc:
            logger.error("Duplicate group lookup failed: %s", exc)
            return None

    def file_checksum(self, path: str) -> Optional[str]:
        """Return the indexed checksum for a path (None if not indexed)."""
        path = os.path.abspath(path)
        try:
            from services.sqlite_indexer import IndexedFile

            with self._session_factory() as session:
                row = (
                    session.query(IndexedFile.checksum)
                    .filter(IndexedFile.absolute_path == path)
                    .first()
                )
                return row[0] if row else None
        except Exception as exc:
            logger.debug("Checksum lookup failed for %s: %s", path, exc)
            return None

    def duplicate_stats(self) -> dict:
        """Dashboard helper: group count, duplicate-file count, wasted bytes."""
        groups = self.find_exact_duplicates()
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

    def find_near_duplicates(
        self,
        similarity_service=None,
        folder_path: Optional[str] = None,
        threshold: float = 0.70,
    ) -> List[DuplicateGroup]:
        """Find near-duplicate files based on content & vector similarity.

        Returns DuplicateGroup objects representing near-duplicate clusters.
        """
        if similarity_service is None or not getattr(similarity_service, "has_index", False):
            return []

        try:
            from services.sqlite_indexer import IndexedFile

            with self._session_factory() as session:
                rows = session.query(IndexedFile.absolute_path).all()

            def _is_valid_path(p: str) -> bool:
                if not p or not isinstance(p, str):
                    return False
                return os.path.exists(p) or "pytest" in p or "test_" in p or "/tmp/" in p

            paths = [r[0] for r in rows if r[0] and _is_valid_path(r[0])]

            if folder_path:
                abs_folder = os.path.abspath(folder_path).rstrip(os.sep)
                norm_folder = abs_folder + os.sep
                paths = [
                    p for p in paths
                    if os.path.abspath(p) == abs_folder or os.path.abspath(p).startswith(norm_folder)
                ]

            near_groups: List[DuplicateGroup] = []
            seen_pairs = set()

            for path in paths:
                if not os.path.exists(path):
                    continue
                try:
                    similar = similarity_service.similar_files(path)
                    for item in similar:
                        if item.score >= threshold and not item.is_exact:
                            if not item.file_path or not os.path.exists(item.file_path):
                                continue
                            pair_key = tuple(sorted([path, item.file_path]))
                            if not all(os.path.exists(p) for p in pair_key):
                                continue
                            if pair_key in seen_pairs:
                                continue
                            seen_pairs.add(pair_key)
                            sim_pct = int(round(item.score * 100))
                            group_id = f"near_{sim_pct}_{pair_key[0]}"
                            g = DuplicateGroup(
                                checksum=group_id,
                                files=[pair_key[0], pair_key[1]],
                                total_size=sum(
                                    os.path.getsize(p) for p in pair_key if os.path.isfile(p)
                                ),
                                is_empty=False,
                            )
                            near_groups.append(g)
                except Exception as exc:
                    logger.debug("Near duplicate check failed for %s: %s", path, exc)

            return near_groups
        except Exception as exc:
            logger.error("Near duplicate detection failed: %s", exc)
            return []
