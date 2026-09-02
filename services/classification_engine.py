"""Classification engine — B5-01.

Normalizes the free-form ``ai_analysis.category`` into a small, deterministic
controlled taxonomy so every analyzed file has a consistent, searchable
category. The pipeline is:

    File
     ↓
    existing AI analysis (or deterministic rules)
     ↓
    taxonomy normalization
     ↓
    persist normalized_category + classification_version

Deterministic rules always run first (extension + keywords), so files can be
classified even when Ollama is unavailable. A file is only re-processed when
its content hash or the classification version changed (Batch 5 §11).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import List, Optional

from engines.config import CLASSIFICATION_BATCH_SIZE, CLASSIFICATION_TAXONOMY, CLASSIFICATION_VERSION

logger = logging.getLogger(__name__)

# Keyword groups per taxonomy category — used both for LLM-category mapping
# and for deterministic keyword classification of file names/content.
_TAXONOMY_KEYWORDS: dict = {
    "code": ["python", "java", "javascript", "typescript", "source", "code",
             "script", "program", "function", "class", "api", "sdk", "library",
             "technical", "tech", "software", "programming", "engineering",
             "developer", "implementation"],
    "presentation": ["slides", "deck", "presentation", "keynote", "pitch", "slideshow"],
    "spreadsheet": ["spreadsheet", "excel", "sheet", "budget", "finance", "invoice",
                    "ledger", "database of", "tabular"],
    "research": ["research", "paper", "study", "journal", "thesis", "experiment",
                 "findings", "analysis of", "literature", "survey"],
    "education": ["lesson", "course", "syllabus", "lecture", "tutorial", "training",
                  "homework", "exam", "curriculum", "workshop"],
    "project": ["project", "roadmap", "milestone", "backlog", "sprint", "proposal",
                "plan", "charter", "spec", "requirements"],
    "business": ["business", "report", "invoice", "contract", "proposal", "financial",
                 "meeting", "minutes", "memo", "marketing", "sales", "client"],
    "personal": ["personal", "resume", "cv", "letter", "diary", "journal entry",
                 "family", "budget"],
    "archive": ["archive", "backup", "log", "history", "old", "legacy"],
    "document": ["document", "doc", "letter", "memo", "text", "article", "manual",
                 "guide", "readme", "note", "brief"],
    "image": ["photo", "picture", "image", "screenshot", "diagram", "graphic"],
    "audio": ["audio", "recording", "podcast", "music", "song", "interview"],
    "video": ["video", "clip", "footage", "movie", "tutorial video", "screen recording"],
}

# Extension → taxonomy mapping (deterministic fallback).
_EXT_CATEGORY: dict = {
    ".py": "code", ".js": "code", ".ts": "code", ".java": "code", ".cpp": "code",
    ".c": "code", ".h": "code", ".rs": "code", ".go": "code", ".rb": "code",
    ".php": "code", ".sh": "code", ".bash": "code", ".sql": "code", ".html": "code",
    ".css": "code", ".jsx": "code", ".tsx": "code",
    ".ppt": "presentation", ".pptx": "presentation", ".key": "presentation",
    ".xls": "spreadsheet", ".xlsx": "spreadsheet", ".csv": "spreadsheet",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image", ".bmp": "image", ".tiff": "image", ".svg": "image",
    ".mp3": "audio", ".wav": "audio", ".flac": "audio", ".ogg": "audio",
    ".m4a": "audio", ".aac": "audio", ".opus": "audio",
    ".mp4": "video", ".mkv": "video", ".mov": "video", ".avi": "video",
    ".webm": "video", ".m4v": "video",
    ".pdf": "document", ".txt": "document", ".md": "document", ".log": "document",
    ".json": "document", ".xml": "document", ".yaml": "document", ".yml": "document",
    ".doc": "document", ".docx": "document", ".rst": "document",
}


def normalize_category(value: Optional[str]) -> str:
    """Map a free-form category (LLM or user) onto the controlled taxonomy.

    Always returns a member of ``CLASSIFICATION_TAXONOMY`` (defaults to
    ``other`` when nothing matches).
    """
    if not value:
        return "other"
    text = value.strip().lower()
    if not text:
        return "other"

    # Exact or near-exact match first.
    for cat in CLASSIFICATION_TAXONOMY:
        if text == cat or text in (cat + "s", cat + "es"):
            return cat

    # Keyword scoring against the taxonomy groups.
    best_cat = "other"
    best_score = 0
    for cat, keywords in _TAXONOMY_KEYWORDS.items():
        if cat not in CLASSIFICATION_TAXONOMY:
            continue
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat


def category_from_extension(path: str) -> str:
    """Deterministic category by file extension (fallback when no AI)."""
    ext = os.path.splitext(path)[1].lower()
    return _EXT_CATEGORY.get(ext, "other")


def category_from_filename(path: str) -> str:
    """Deterministic category by filename keywords."""
    name = os.path.basename(path).lower()
    best_cat = "other"
    best_score = 0
    for cat, keywords in _TAXONOMY_KEYWORDS.items():
        if cat not in CLASSIFICATION_TAXONOMY:
            continue
        score = sum(1 for kw in keywords if kw in name)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat


class ClassificationEngine:
    """Classifies files into the controlled taxonomy."""

    def __init__(
        self,
        session_factory,
        analysis_cache=None,
        ai_service=None,
        batch_size: int = CLASSIFICATION_BATCH_SIZE,
        version: str = CLASSIFICATION_VERSION,
    ) -> None:
        """Args:
            session_factory: DB session factory.
            analysis_cache: AICacheManager (optional — used for AI metadata).
            ai_service: AIService (optional — used to generate analysis when
                a file has none and Ollama is available).
            batch_size: files per LLM batch call.
            version: classification version for cache invalidation.
        """
        self._session_factory = session_factory
        self._cache = analysis_cache
        self._ai_service = ai_service
        self._batch_size = batch_size
        self._version = version

    # ------------------------------------------------------------------ #
    def classify_file(self, file_path: str) -> Optional[str]:
        """Classify one file; returns the normalized category or None."""
        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            return None

        category = self._deterministic_category(file_path)
        analysis = self._get_analysis(file_path)
        if analysis is not None:
            llm_cat = normalize_category(analysis.get("category"))
            if llm_cat != "other" or category == "other":
                category = llm_cat

        self._persist(file_path, category)
        return category

    def _deterministic_category(self, file_path: str) -> str:
        """Extension-first, then filename keywords."""
        ext_cat = category_from_extension(file_path)
        if ext_cat != "other":
            return ext_cat
        return category_from_filename(file_path)

    def _get_analysis(self, file_path: str) -> Optional[dict]:
        """Load AI analysis for a file (by content hash), or generate one."""
        if self._cache is None:
            return None
        from services.file_identity import calculate_sha256_safe

        file_hash = calculate_sha256_safe(file_path)
        if not file_hash:
            return None
        analysis = self._cache.get_analysis(file_hash)
        if analysis is not None:
            return analysis
        # No cached analysis — only generate when an AI service is available
        # and the file is text-extractable.
        if self._ai_service is None:
            return None
        try:
            from ai.analysis_manager import AnalysisManager

            manager = AnalysisManager(self._ai_service)
            result = manager.analyze_file(file_path)
            if "error" in result:
                return None
            return result
        except Exception as exc:
            logger.debug("AI analysis generation failed for %s: %s", file_path, exc)
            return None

    def _persist(self, file_path: str, category: str) -> None:
        """Persist normalized category + version on the ai_analysis row."""
        try:
            from services.file_identity import calculate_sha256_safe

            file_hash = calculate_sha256_safe(file_path)
            if not file_hash:
                return
            from database.models import AIAnalysis

            with self._session_factory() as session:
                row = (
                    session.query(AIAnalysis)
                    .filter(AIAnalysis.file_hash == file_hash)
                    .first()
                )
                if row is None:
                    # No AI analysis row yet — store classification only.
                    row = AIAnalysis(
                        file_hash=file_hash,
                        normalized_category=category,
                        classification_version=self._version,
                        classified_at=datetime.now(),
                    )
                    session.add(row)
                else:
                    row.normalized_category = category
                    row.classification_version = self._version
                    row.classified_at = datetime.now()
                session.commit()
        except Exception as exc:
            logger.error("Failed to persist classification for %s: %s", file_path, exc)

    # ------------------------------------------------------------------ #
    def classify_batch(
        self,
        paths: List[str],
        progress_callback=None,
        cancel_event=None,
    ) -> dict:
        """Classify many files, honoring cancellation and progress.

        Returns {"classified": n, "skipped": n, "errors": n}.
        """
        classified = skipped = errors = 0
        total = len(paths)
        for i, path in enumerate(paths):
            if cancel_event and cancel_event.is_set():
                break
            if progress_callback:
                progress_callback(i + 1, total)
            try:
                if self.is_current(path):
                    skipped += 1
                    continue
                if self.classify_file(path) is not None:
                    classified += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                logger.debug("Classification failed for %s: %s", path, exc)
        return {"classified": classified, "skipped": skipped, "errors": errors}

    def is_current(self, file_path: str) -> bool:
        """True when the file's stored classification matches this version."""
        try:
            from services.file_identity import calculate_sha256_safe

            file_hash = calculate_sha256_safe(file_path)
            if not file_hash:
                return False
            from database.models import AIAnalysis

            with self._session_factory() as session:
                row = (
                    session.query(AIAnalysis)
                    .filter(AIAnalysis.file_hash == file_hash)
                    .first()
                )
                return bool(
                    row
                    and row.normalized_category
                    and row.classification_version == self._version
                )
        except Exception:
            return False

    def category_for_path(self, file_path: str) -> Optional[str]:
        """Read the persisted normalized category for a path."""
        try:
            from services.file_identity import calculate_sha256_safe

            file_hash = calculate_sha256_safe(file_path)
            if not file_hash:
                return None
            from database.models import AIAnalysis

            with self._session_factory() as session:
                row = (
                    session.query(AIAnalysis)
                    .filter(AIAnalysis.file_hash == file_hash)
                    .first()
                )
                return row.normalized_category if row else None
        except Exception:
            return None

    def categories_in_workspace(self) -> dict:
        """Dashboard helper: category → file count (only classified files)."""
        try:
            from services.sqlite_indexer import IndexedFile

            with self._session_factory() as session:
                rows = session.query(IndexedFile.checksum).all()
                hashes = {r[0] for r in rows if r[0]}
            if not hashes:
                return {}
            from database.models import AIAnalysis

            with self._session_factory() as session:
                classified = (
                    session.query(AIAnalysis.normalized_category)
                    .filter(
                        AIAnalysis.normalized_category.isnot(None),
                        AIAnalysis.normalized_category != "",
                        AIAnalysis.file_hash.in_(hashes),
                    )
                    .all()
                )
            counts: dict = {}
            for (cat,) in classified:
                counts[cat] = counts.get(cat, 0) + 1
            return counts
        except Exception as exc:
            logger.debug("Workspace categories failed: %s", exc)
            return {}
