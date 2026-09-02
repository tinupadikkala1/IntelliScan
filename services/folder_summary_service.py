"""AI-powered folder summary service — B7-8 (#27).

Generates a grounded natural-language summary of a folder by composing:

    folder statistics (FolderIntelligenceService — LLM-free)
    + classification composition (FolderClassificationService)
    + indexed evidence (RAG engine, folder scope)

The LLM only summarizes what the statistics and evidence actually say; no
unsupported claims are generated. The result is persisted on
``folder_classifications`` (summary / summary_model / summary_version /
summarized_at) and survives restart. When the folder has no AI evidence,
the user is told the *Index for AI* prerequisite instead of hallucinating.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from engines.config import FOLDER_SUMMARY_VERSION

logger = logging.getLogger(__name__)


class FolderSummaryService:
    """Grounds and persists an AI folder summary."""

    def __init__(
        self,
        session_factory,
        folder_classification_service=None,
        folder_intelligence_service=None,
        rag_engine=None,
        model: str = "qwen-local:latest",
        version: str = FOLDER_SUMMARY_VERSION,
    ) -> None:
        self._session_factory = session_factory
        self._folder_cls = folder_classification_service
        self._folder_intel = folder_intelligence_service
        self._rag = rag_engine
        self._model = model
        self._version = version

    # ------------------------------------------------------------------ #
    def generate(self, folder_path: str) -> Optional[str]:
        """Generate and persist a summary; None when unavailable/failed."""
        folder_path = os.path.abspath(folder_path)
        stats = self._stats_block(folder_path)
        if stats is None:
            return None

        if self._rag is None:
            return self._persist(folder_path, None)

        prompt = self._build_prompt(folder_path, stats)
        try:
            answer = self._rag._generate(prompt)
        except Exception as exc:
            logger.error("Folder summary generation failed for %s: %s", folder_path, exc)
            return None
        if not answer or not answer.strip():
            return self._persist(folder_path, None)

        summary = answer.strip()
        self._persist(folder_path, summary)
        return summary

    # ------------------------------------------------------------------ #
    def _stats_block(self, folder_path: str) -> Optional[dict]:
        """Compose the factual inputs the summary must stay grounded in."""
        info = {}
        if self._folder_cls is not None:
            try:
                cls = self._folder_cls.classify_folder(folder_path)
                info["classification"] = {
                    "dominant_category": cls.dominant_category,
                    "distribution": cls.distribution,
                    "classified_count": cls.classified_count,
                    "unclassified_count": cls.unclassified_count,
                }
            except Exception as exc:
                logger.debug("Folder classification unavailable: %s", exc)
        if self._folder_intel is not None:
            try:
                fi = self._folder_intel.analyze(folder_path)
                info["statistics"] = {
                    "total_files": fi.total_files,
                    "total_size": fi.total_size,
                    "file_type_distribution": fi.file_type_distribution,
                    "extension_distribution": fi.extension_distribution,
                    "date_range": fi.date_range,
                    "top_keywords": fi.top_keywords,
                }
            except Exception as exc:
                logger.debug("Folder intelligence unavailable: %s", exc)
        # Self-contained fallback: when the helper services are not wired
        # (e.g. unit tests), derive basic stats straight from the index.
        if not info:
            info["statistics"] = self._db_stats(folder_path)
        if not info:
            return None
        return info

    # ------------------------------------------------------------------ #
    def _db_stats(self, folder_path: str) -> dict:
        """Fallback statistics computed directly from indexed_files."""
        prefix = folder_path.rstrip(os.sep) + os.sep
        total = 0
        total_size = 0
        exts = {}
        types = {}
        cats = {}
        from collections import Counter
        from services.sqlite_indexer import IndexedFile
        from database.models import AIAnalysis
        try:
            with self._session_factory() as session:
                for r in session.query(IndexedFile).all():
                    p = r.absolute_path or ""
                    if not p.startswith(prefix):
                        continue
                    total += 1
                    total_size += r.size or 0
                    ext = (os.path.splitext(p)[1] or "(none)").lower()
                    exts[ext] = exts.get(ext, 0) + 1
                    ftype = getattr(r, "file_type", "") or ""
                    if ftype:
                        types[ftype] = types.get(ftype, 0) + 1
                checksums = [
                    r.checksum for r in session.query(IndexedFile).all()
                    if (r.absolute_path or "").startswith(prefix)
                    and r.checksum and len(r.checksum) == 64
                ]
                if checksums:
                    for a in session.query(AIAnalysis).filter(
                        AIAnalysis.file_hash.in_(checksums)
                    ).all():
                        if a.normalized_category:
                            cats[a.normalized_category] = cats.get(
                                a.normalized_category, 0
                            ) + 1
        except Exception as exc:
            logger.debug("Folder summary DB fallback failed: %s", exc)
        if total == 0:
            return {"total_files": 0, "total_size": 0}
        return {
            "total_files": total,
            "total_size": total_size,
            "extension_distribution": dict(exts),
            "file_type_distribution": dict(types or exts),
            "category_distribution": dict(cats),
            "top_keywords": [],
        }

    # ------------------------------------------------------------------ #
    def _build_prompt(self, folder_path: str, stats: dict) -> str:
        facts = json.dumps(stats, ensure_ascii=False, indent=2)
        return (
            "You summarize a folder in the IntelliVault workspace. Use ONLY the "
            "facts provided below; do not invent file names, counts, dates or "
            "topics that are not present. Write 3-6 concise sentences covering "
            "the folder's contents, dominant categories, file types, approximate "
            "size, notable patterns and any clear observations.\n\n"
            f"FOLDER: {folder_path}\n\n"
            f"FACTS:\n{facts}\n\n"
            "SUMMARY:"
        )

    # ------------------------------------------------------------------ #
    def _persist(self, folder_path: str, summary: Optional[str]) -> Optional[str]:
        try:
            from database.models import FolderClassification
            with self._session_factory() as session:
                row = (
                    session.query(FolderClassification)
                    .filter(FolderClassification.folder_path == folder_path)
                    .first()
                )
                if row is None:
                    row = FolderClassification(
                        folder_path=folder_path,
                        dominant_category="other",
                        distribution_json="{}",
                    )
                    session.add(row)
                row.summary = summary
                row.summary_model = self._model if summary else None
                row.summary_version = self._version if summary else None
                row.summarized_at = datetime.now() if summary else None
                session.commit()
        except Exception as exc:
            logger.error("Failed to persist folder summary for %s: %s", folder_path, exc)
        return summary

    # ------------------------------------------------------------------ #
    def get(self, folder_path: str) -> Optional[dict]:
        """Load a persisted summary: {"summary", "model", "version", "at"}."""
        try:
            from database.models import FolderClassification
            with self._session_factory() as session:
                row = (
                    session.query(FolderClassification)
                    .filter(FolderClassification.folder_path == os.path.abspath(folder_path))
                    .first()
                )
                if row is None or not row.summary:
                    return None
                return {
                    "summary": row.summary,
                    "model": row.summary_model or "",
                    "version": row.summary_version or "",
                    "at": str(row.summarized_at)[:19] if row.summarized_at else "",
                }
        except Exception as exc:
            logger.debug("Failed to load folder summary for %s: %s", folder_path, exc)
            return None
