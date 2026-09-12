"""File cleanup orchestration — one removal path for deleted files.

Batch 5 §3.1. Deleted files previously remained as stale rows in
``indexed_files``, corrupting duplicate counts, related-file results,
collection membership, organization suggestions and dashboard statistics.

Every deletion flows through :func:`cleanup_deleted_file`, which removes:

1. the ``indexed_files`` row (Batch 1 index),
2. AI evidence + vector mappings + FAISS vectors (via retrieval/db_store),
3. knowledge-graph data derived from the file (GraphStore.remove_file),
4. file relationships (both source and target edges),
5. collection membership (static + smart memberships for the path),
6. organization suggestions targeting the path.

AI *analysis* (``ai_analysis``) is keyed by content hash, not path, and may
be shared by other copies of the same content — it is intentionally left
alone here (reindexing identical content reuses it).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from engines.config import SKIP_EXTENSIONS

logger = logging.getLogger(__name__)


def _remove_indexed_row(session_factory, abs_path: str) -> bool:
    """Delete the indexed_files row for a path. Returns True if removed."""
    try:
        from services.sqlite_indexer import IndexedFile

        with session_factory() as session:
            record = (
                session.query(IndexedFile)
                .filter_by(absolute_path=abs_path)
                .first()
            )
            if record is None:
                return False
            session.delete(record)
            session.commit()
            return True
    except Exception as exc:
        logger.error("Failed to remove indexed row for %s: %s", abs_path, exc)
        return False


def _remove_relationships(session_factory, abs_path: str) -> int:
    """Remove file_relationships edges touching a path."""
    try:
        from database.models import FileRelationship

        with session_factory() as session:
            count = (
                session.query(FileRelationship)
                .filter(
                    (FileRelationship.source_path == abs_path)
                    | (FileRelationship.target_path == abs_path)
                )
                .delete(synchronize_session=False)
            )
            session.commit()
            return count or 0
    except Exception as exc:
        logger.error("Failed to remove relationships for %s: %s", abs_path, exc)
        return 0


def _remove_collection_membership(session_factory, abs_path: str) -> int:
    """Remove collection membership rows for a path (smart or static)."""
    try:
        from database.models import CollectionItem

        with session_factory() as session:
            count = (
                session.query(CollectionItem)
                .filter(CollectionItem.file_path == abs_path)
                .delete(synchronize_session=False)
            )
            session.commit()
            return count or 0
    except Exception as exc:
        logger.error("Failed to remove collection membership for %s: %s", abs_path, exc)
        return 0


def _remove_suggestions(session_factory, abs_path: str) -> int:
    """Remove organization suggestions for a path."""
    try:
        from database.models import OrganizationSuggestion

        with session_factory() as session:
            count = (
                session.query(OrganizationSuggestion)
                .filter(OrganizationSuggestion.file_path == abs_path)
                .delete(synchronize_session=False)
            )
            session.commit()
            return count or 0
    except Exception as exc:
        logger.error("Failed to remove suggestions for %s: %s", abs_path, exc)
        return 0


def _remove_duplicate_suggestions(session_factory, abs_path: str) -> int:
    """Remove duplicate recommendations that reference a deleted path."""
    try:
        from database.models import DuplicateSuggestion

        with session_factory() as session:
            count = (
                session.query(DuplicateSuggestion)
                .filter(
                    (DuplicateSuggestion.keep_path == abs_path)
                    | (DuplicateSuggestion.remove_path == abs_path)
                )
                .delete(synchronize_session=False)
            )
            session.commit()
            return count or 0
    except Exception as exc:
        logger.error(
            "Failed to remove duplicate suggestions for %s: %s", abs_path, exc
        )
        return 0


def _verify_database_cleanup(session_factory, abs_path: str) -> list[str]:
    """Return persisted layers that still reference a deleted path."""
    remaining: list[str] = []
    try:
        from database.models import (
            CollectionItem,
            DuplicateSuggestion,
            Evidence,
            FileRelationship,
            OrganizationSuggestion,
            VectorMap,
        )
        from services.sqlite_indexer import IndexedFile

        with session_factory() as session:
            checks = (
                ("indexed_files", session.query(IndexedFile).filter(
                    IndexedFile.absolute_path == abs_path
                ).first()),
                ("evidence", session.query(Evidence).filter(
                    Evidence.file_path == abs_path
                ).first()),
                ("vector_map", session.query(VectorMap).filter(
                    VectorMap.file_path == abs_path
                ).first()),
                ("relationships", session.query(FileRelationship).filter(
                    (FileRelationship.source_path == abs_path)
                    | (FileRelationship.target_path == abs_path)
                ).first()),
                ("collection_members", session.query(CollectionItem).filter(
                    CollectionItem.file_path == abs_path
                ).first()),
                ("suggestions", session.query(OrganizationSuggestion).filter(
                    OrganizationSuggestion.file_path == abs_path
                ).first()),
                ("duplicate_suggestions", session.query(DuplicateSuggestion).filter(
                    (DuplicateSuggestion.keep_path == abs_path)
                    | (DuplicateSuggestion.remove_path == abs_path)
                ).first()),
            )
            remaining.extend(name for name, row in checks if row is not None)
    except Exception as exc:
        logger.error("Could not verify cleanup for %s: %s", abs_path, exc)
        remaining.append(f"verification: {exc}")
    return remaining


def cleanup_deleted_file(
    abs_path: str,
    session_factory=None,
    retrieval=None,
    db_store=None,
    graph_engine=None,
    vector_engine=None,
) -> dict:
    """Orchestrated cleanup for a confirmed-deleted file.

    Safe to call when the path is already gone or never existed; every step
    is individually guarded so one failure never blocks the others.

    Returns a dict with per-layer removal counts:
        {"indexed_row": bool, "evidence_chunks": int, "graph_links": int,
         "relationships": int, "collection_members": int, "suggestions": int}
    """
    abs_path = os.path.abspath(abs_path)
    report: dict = {
        "indexed_row": False,
        "evidence_chunks": 0,
        "graph_links": 0,
        "relationships": 0,
        "collection_members": 0,
        "suggestions": 0,
        "duplicate_suggestions": 0,
        "errors": [],
    }

    # 1. Batch-1 index row.
    if session_factory is not None:
        report["indexed_row"] = _remove_indexed_row(session_factory, abs_path)

    # 2. AI evidence + vectors + FAISS.
    if retrieval is not None:
        try:
            report["evidence_chunks"] = retrieval.remove_file(abs_path)
        except Exception as exc:
            logger.error("Failed to remove AI evidence for %s: %s", abs_path, exc)
            report["errors"].append(f"evidence: {exc}")
    if db_store is not None:
        try:
            db_store.delete_evidence_by_file(abs_path)
        except Exception as exc:
            logger.error("Failed to remove DB evidence for %s: %s", abs_path, exc)
            report["errors"].append(f"database evidence: {exc}")

    # 3. Knowledge graph.
    if graph_engine is not None:
        try:
            report["graph_links"] = graph_engine.remove_file(abs_path)
        except Exception as exc:
            logger.error("Failed to remove graph data for %s: %s", abs_path, exc)
            report["errors"].append(f"graph: {exc}")

    # 4. File relationships (both directions).
    if session_factory is not None:
        report["relationships"] = _remove_relationships(session_factory, abs_path)

    # 5. Collection membership.
    if session_factory is not None:
        report["collection_members"] = _remove_collection_membership(session_factory, abs_path)

    # 6. Organization suggestions.
    if session_factory is not None:
        report["suggestions"] = _remove_suggestions(session_factory, abs_path)
        report["duplicate_suggestions"] = _remove_duplicate_suggestions(
            session_factory, abs_path
        )
        report["errors"].extend(
            f"database layer still references deleted path: {layer}"
            for layer in _verify_database_cleanup(session_factory, abs_path)
        )

    # Persist the trimmed FAISS index once at the end.
    if vector_engine is not None and (report["evidence_chunks"] or report["indexed_row"]):
        try:
            vector_engine.save()
        except Exception as exc:
            logger.error("Failed to save FAISS index after cleanup: %s", exc)
            report["errors"].append(f"vector index: {exc}")

    report["status"] = "completed_with_errors" if report["errors"] else "completed"
    logger.info("Cleanup for deleted %s: %s", abs_path, report)
    return report


def is_ai_indexable_path(path: str) -> bool:
    """True when a path could carry AI-derived state (evidence/vectors)."""
    ext = os.path.splitext(path)[1].lower()
    return bool(ext) and ext not in SKIP_EXTENSIONS


def cleanup_all_stale_files(
    session_factory,
    retrieval=None,
    db_store=None,
    graph_engine=None,
    vector_engine=None,
    progress_callback=None,
) -> dict:
    """Bulk scan and purge all database records pointing to non-existent files on disk.

    Scans IndexedFile, Evidence, FileRelationship, CollectionItem,
    OrganizationSuggestion, and DuplicateSuggestion tables.

    Returns:
        Summary dict containing counts of stale files cleaned and deleted rows.
    """
    if session_factory is None:
        return {"stale_files": 0, "status": "no_db"}

    stale_paths: set[str] = set()

    try:
        from database.models import (
            CollectionItem,
            DuplicateSuggestion,
            FileRelationship,
            OrganizationSuggestion,
        )
        from services.sqlite_indexer import IndexedFile

        with session_factory() as session:
            # 1. Check IndexedFile table
            rows = session.query(IndexedFile.absolute_path).all()
            for (p,) in rows:
                if p and not os.path.exists(p):
                    stale_paths.add(os.path.abspath(p))

            # 2. Check FileRelationship table
            rel_rows = session.query(FileRelationship.source_path, FileRelationship.target_path).all()
            for sp, tp in rel_rows:
                if sp and not os.path.exists(sp):
                    stale_paths.add(os.path.abspath(sp))
                if tp and not os.path.exists(tp):
                    stale_paths.add(os.path.abspath(tp))

            # 3. Check CollectionItem table
            ci_rows = session.query(CollectionItem.file_path).all()
            for (cp,) in ci_rows:
                if cp and not os.path.exists(cp):
                    stale_paths.add(os.path.abspath(cp))

            # 4. Check OrganizationSuggestion table
            os_rows = session.query(OrganizationSuggestion.file_path).all()
            for (op,) in os_rows:
                if op and not os.path.exists(op):
                    stale_paths.add(os.path.abspath(op))

            # 5. Check Evidence table (AI evidence / FAISS chunk paths)
            try:
                from database.models import Evidence
                ev_rows = session.query(Evidence.file_path).distinct().all()
                for (ep,) in ev_rows:
                    if ep and not os.path.exists(ep):
                        stale_paths.add(os.path.abspath(ep))
            except Exception as exc:
                logger.debug("Evidence stale path check skipped: %s", exc)

            # 6. Check DuplicateSuggestion table (remove stale suggestions)
            ds_rows = session.query(DuplicateSuggestion.id, DuplicateSuggestion.keep_path, DuplicateSuggestion.remove_path).all()
            stale_ds_ids = [
                ds_id for ds_id, kp, rp in ds_rows
                if (kp and not os.path.exists(kp)) or (rp and not os.path.exists(rp))
            ]
            if stale_ds_ids:
                session.query(DuplicateSuggestion).filter(DuplicateSuggestion.id.in_(stale_ds_ids)).delete(synchronize_session=False)
                session.commit()

    except Exception as exc:
        logger.error("Failed to identify stale database paths: %s", exc)

    total_stale = len(stale_paths)
    logger.info("Found %d stale file paths to clean in database", total_stale)

    cleaned_count = 0
    total_evidence_chunks = 0
    total_relationships = 0

    for idx, path in enumerate(stale_paths):
        if progress_callback:
            progress_callback(idx + 1, total_stale)
        rep = cleanup_deleted_file(
            abs_path=path,
            session_factory=session_factory,
            retrieval=retrieval,
            db_store=db_store,
            graph_engine=graph_engine,
            vector_engine=vector_engine,
        )
        if rep.get("indexed_row") or rep.get("evidence_chunks") or rep.get("relationships"):
            cleaned_count += 1
            total_evidence_chunks += rep.get("evidence_chunks", 0)
            total_relationships += rep.get("relationships", 0)

    if vector_engine is not None and total_evidence_chunks > 0:
        try:
            vector_engine.save()
        except Exception as exc:
            logger.error("Failed to save vector engine after bulk stale cleanup: %s", exc)

    return {
        "stale_files": total_stale,
        "cleaned_files": cleaned_count,
        "evidence_chunks_removed": total_evidence_chunks,
        "relationships_removed": total_relationships,
    }
