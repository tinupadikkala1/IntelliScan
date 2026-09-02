"""Approved file-move service — B6-05 (#29).

Executes a user-approved move and keeps every derived layer in sync so the
SHA-256 identity and all associated state survive:

    approve
      ↓ validate source + destination
      ↓ collision check (never overwrite silently)
      ↓ shutil.move
      ↓ indexed_files path update (checksum preserved)
      ↓ evidence + vector_map path updates (FAISS vectors untouched — they
        resolve through vector_map)
      ↓ file_relationships / collection_items / organization_suggestions /
        duplicate_suggestions path updates
      ↓ in-memory retrieval evidence path updates
      ↓ report

This is the *only* code path that moves files as a result of organization;
it is always preceded by explicit user approval in the preview dialog.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MoveResult:
    """Outcome of one approved file move."""

    ok: bool
    source: str = ""
    destination: str = ""
    error: str = ""
    counts: dict = field(default_factory=dict)  # per-layer updated rows


class MoveError(Exception):
    """Raised for user-facing move failures (never overwrites silently)."""


def move_file(
    src: str,
    dst_dir: str,
    session_factory=None,
    retrieval=None,
    vector_engine=None,
) -> MoveResult:
    """Move ``src`` into ``dst_dir`` and synchronize all derived state."""
    src = os.path.abspath(src)
    dst_dir = os.path.abspath(dst_dir)
    counts: dict = {}

    # ---- Validation --------------------------------------------------- #
    if not os.path.isfile(src):
        raise MoveError(f"The source file no longer exists: {src}")
    if not os.path.isdir(dst_dir):
        raise MoveError(f"The destination folder does not exist: {dst_dir}")
    if os.path.dirname(src) == dst_dir:
        raise MoveError("The file is already in that folder.")

    target = os.path.join(dst_dir, os.path.basename(src))
    if os.path.exists(target):
        raise MoveError(
            f"'{os.path.basename(src)}' already exists in the destination. "
            "The file was not moved (nothing was overwritten)."
        )

    # ---- Perform the move --------------------------------------------- #
    try:
        shutil.move(src, target)
    except OSError as exc:
        raise MoveError(f"Cannot move file: {exc}") from exc

    # ---- Synchronize derived layers ----------------------------------- #
    if session_factory is not None:
        counts.update(_sync_indexed_row(session_factory, src, target))
        counts.update(_sync_evidence_paths(session_factory, src, target))
        counts.update(_sync_vector_map_paths(session_factory, src, target))
        counts.update(_sync_relationships(session_factory, src, target))
        counts.update(_sync_collection_items(session_factory, src, target))
        counts.update(_sync_organization_suggestions(session_factory, src, target))
        counts.update(_sync_duplicate_suggestions(session_factory, src, target))
        counts.update(_sync_legacy_files_table(session_factory, src, target))

    # In-memory retrieval evidence must follow the new path too.
    if retrieval is not None:
        try:
            moved = 0
            for chunk in list(retrieval._evidence.values()):
                if chunk.file_path == src:
                    chunk.file_path = target
                    moved += 1
            counts["evidence_in_memory"] = moved
        except Exception as exc:
            logger.error("Failed to update in-memory evidence paths: %s", exc)

    logger.info("Moved %s → %s (%s)", src, target, counts)
    return MoveResult(ok=True, source=src, destination=target, counts=counts)


def rename_file(
    src: str,
    new_name: str,
    session_factory=None,
    retrieval=None,
    vector_engine=None,
) -> MoveResult:
    """Rename ``src`` to ``new_name`` inside its own directory (B7-9).

    Same safety guarantees as :func:`move_file`: validates the new name,
    never overwrites, preserves SHA-256, and synchronizes every derived
    layer. This is the only approved rename path.
    """
    src = os.path.abspath(src)
    if not new_name or not new_name.strip():
        raise MoveError("The new name is empty.")
    if "/" in new_name or "\\" in new_name or new_name in (".", ".."):
        raise MoveError("The new name is not a valid file name.")
    base = os.path.basename(new_name.strip())
    if base != new_name.strip():
        raise MoveError("The new name must be a plain file name.")
    if not os.path.isfile(src):
        raise MoveError(f"The source file no longer exists: {src}")
    if base == os.path.basename(src):
        raise MoveError("The name is unchanged.")

    ext_cur = os.path.splitext(os.path.basename(src))[1].lower()
    ext_new = os.path.splitext(base)[1].lower()
    if ext_cur and ext_new != ext_cur:
        raise MoveError(
            f"Extension change is not allowed ({ext_cur} → {ext_new}). "
            "The file was not renamed."
        )
    if not ext_cur and ext_new:
        raise MoveError("Extension change is not allowed.")

    target = os.path.join(os.path.dirname(src), base)
    if os.path.exists(target):
        raise MoveError(
            f"'{base}' already exists in that folder. The file was not renamed "
            "(nothing was overwritten)."
        )

    try:
        os.rename(src, target)
    except OSError as exc:
        raise MoveError(f"Cannot rename file: {exc}") from exc

    counts: dict = {}
    if session_factory is not None:
        counts.update(_sync_indexed_row(session_factory, src, target))
        counts.update(_sync_evidence_paths(session_factory, src, target))
        counts.update(_sync_vector_map_paths(session_factory, src, target))
        counts.update(_sync_relationships(session_factory, src, target))
        counts.update(_sync_collection_items(session_factory, src, target))
        counts.update(_sync_organization_suggestions(session_factory, src, target))
        counts.update(_sync_duplicate_suggestions(session_factory, src, target))
        counts.update(_sync_legacy_files_table(session_factory, src, target))

    if retrieval is not None:
        try:
            moved = 0
            for chunk in list(retrieval._evidence.values()):
                if chunk.file_path == src:
                    chunk.file_path = target
                    moved += 1
            counts["evidence_in_memory"] = moved
        except Exception as exc:
            logger.error("Failed to update in-memory evidence paths: %s", exc)

    logger.info("Renamed %s → %s (%s)", src, target, counts)
    return MoveResult(ok=True, source=src, destination=target, counts=counts)


# ---------------------------------------------------------------------- #
# Per-layer path updates (all guarded, never raise on partial failure)
# ---------------------------------------------------------------------- #
def _sync_indexed_row(session_factory, src: str, dst: str) -> dict:
    try:
        from services.sqlite_indexer import IndexedFile

        with session_factory() as session:
            row = session.query(IndexedFile).filter_by(absolute_path=src).first()
            if row is None:
                return {"indexed_files": 0}
            row.absolute_path = dst
            row.filename = os.path.basename(dst)
            row.parent = os.path.dirname(dst)
            # checksum / mime / size / dates intentionally preserved.
            session.commit()
            return {"indexed_files": 1}
    except Exception as exc:
        logger.error("Indexed-row path update failed for %s: %s", src, exc)
        return {"indexed_files": 0}


def _sync_evidence_paths(session_factory, src: str, dst: str) -> dict:
    try:
        from database.models import Evidence

        with session_factory() as session:
            count = (
                session.query(Evidence)
                .filter(Evidence.file_path == src)
                .update({Evidence.file_path: dst}, synchronize_session=False)
            )
            session.commit()
            return {"evidence": count or 0}
    except Exception as exc:
        logger.error("Evidence path update failed for %s: %s", src, exc)
        return {"evidence": 0}


def _sync_vector_map_paths(session_factory, src: str, dst: str) -> dict:
    try:
        from database.models import VectorMap

        with session_factory() as session:
            count = (
                session.query(VectorMap)
                .filter(VectorMap.file_path == src)
                .update({VectorMap.file_path: dst}, synchronize_session=False)
            )
            session.commit()
            return {"vector_map": count or 0}
    except Exception as exc:
        logger.error("Vector-map path update failed for %s: %s", src, exc)
        return {"vector_map": 0}


def _sync_relationships(session_factory, src: str, dst: str) -> dict:
    try:
        from database.models import FileRelationship

        with session_factory() as session:
            src_count = (
                session.query(FileRelationship)
                .filter(FileRelationship.source_path == src)
                .update({FileRelationship.source_path: dst}, synchronize_session=False)
            )
            tgt_count = (
                session.query(FileRelationship)
                .filter(FileRelationship.target_path == src)
                .update({FileRelationship.target_path: dst}, synchronize_session=False)
            )
            session.commit()
            return {"relationships": (src_count or 0) + (tgt_count or 0)}
    except Exception as exc:
        logger.error("Relationship path update failed for %s: %s", src, exc)
        return {"relationships": 0}


def _sync_collection_items(session_factory, src: str, dst: str) -> dict:
    try:
        from database.models import CollectionItem

        with session_factory() as session:
            count = (
                session.query(CollectionItem)
                .filter(CollectionItem.file_path == src)
                .update({CollectionItem.file_path: dst}, synchronize_session=False)
            )
            session.commit()
            return {"collection_items": count or 0}
    except Exception as exc:
        logger.error("Collection-item path update failed for %s: %s", src, exc)
        return {"collection_items": 0}


def _sync_organization_suggestions(session_factory, src: str, dst: str) -> dict:
    try:
        from database.models import OrganizationSuggestion

        with session_factory() as session:
            count = (
                session.query(OrganizationSuggestion)
                .filter(OrganizationSuggestion.file_path == src)
                .update({OrganizationSuggestion.file_path: dst}, synchronize_session=False)
            )
            session.commit()
            return {"suggestions": count or 0}
    except Exception as exc:
        logger.error("Suggestion path update failed for %s: %s", src, exc)
        return {"suggestions": 0}


def _sync_duplicate_suggestions(session_factory, src: str, dst: str) -> dict:
    try:
        from database.models import DuplicateSuggestion

        with session_factory() as session:
            keep = (
                session.query(DuplicateSuggestion)
                .filter(DuplicateSuggestion.keep_path == src)
                .update({DuplicateSuggestion.keep_path: dst}, synchronize_session=False)
            )
            remove = (
                session.query(DuplicateSuggestion)
                .filter(DuplicateSuggestion.remove_path == src)
                .update({DuplicateSuggestion.remove_path: dst}, synchronize_session=False)
            )
            session.commit()
            return {"duplicate_suggestions": (keep or 0) + (remove or 0)}
    except Exception as exc:
        logger.error("Duplicate-suggestion path update failed for %s: %s", src, exc)
        return {"duplicate_suggestions": 0}


def _sync_legacy_files_table(session_factory, src: str, dst: str) -> dict:
    try:
        from database.models import File

        with session_factory() as session:
            row = session.query(File).filter_by(path=src).first()
            if row is None:
                return {"legacy_files": 0}
            row.path = dst
            row.name = os.path.basename(dst)
            row.parent = os.path.dirname(dst)
            session.commit()
            return {"legacy_files": 1}
    except Exception as exc:
        logger.error("Legacy files-table path update failed for %s: %s", src, exc)
        return {"legacy_files": 0}
