"""Folder intelligence service — B7 (#31 completion).

Extends the Batch-6 folder classification (category composition) with
general folder statistics that work without any LLM:

  - total files / total size
  - file-type distribution (modality buckets)
  - extension distribution
  - oldest / newest file and date range
  - classified / unclassified counts (reuses FolderClassificationService)
  - top keywords (from ai_analysis.summary/keywords where available)
  - top categories

Derived live from the Batch-1 index + AI metadata; never fabricates data.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MODALITY_BY_EXT = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".bmp": "image", ".tiff": "image", ".tif": "image", ".gif": "image",
    ".svg": "image",
    ".mp3": "audio", ".wav": "audio", ".flac": "audio", ".ogg": "audio",
    ".aac": "audio", ".m4a": "audio", ".wma": "audio", ".opus": "audio",
    ".mp4": "video", ".mkv": "video", ".mov": "video", ".avi": "video",
    ".webm": "video", ".m4v": "video", ".flv": "video", ".wmv": "video",
}


@dataclass
class FolderIntelligenceInfo:
    """General folder statistics (LLM-free)."""

    folder_path: str
    total_files: int = 0
    total_size: int = 0
    file_type_distribution: Dict[str, int] = field(default_factory=dict)
    extension_distribution: Dict[str, int] = field(default_factory=dict)
    oldest_file: Optional[str] = None
    newest_file: Optional[str] = None
    date_range: str = ""
    classified_count: int = 0
    unclassified_count: int = 0
    dominant_category: str = "other"
    category_distribution: Dict[str, int] = field(default_factory=dict)
    top_keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "folder_path": self.folder_path,
            "total_files": self.total_files,
            "total_size": self.total_size,
            "file_type_distribution": self.file_type_distribution,
            "extension_distribution": self.extension_distribution,
            "oldest_file": self.oldest_file,
            "newest_file": self.newest_file,
            "date_range": self.date_range,
            "classified_count": self.classified_count,
            "unclassified_count": self.unclassified_count,
            "dominant_category": self.dominant_category,
            "category_distribution": self.category_distribution,
            "top_keywords": self.top_keywords,
        }


class FolderIntelligenceService:
    """Computes general folder statistics from the existing index."""

    def __init__(self, session_factory, folder_classification_service=None) -> None:
        self._session_factory = session_factory
        self._folder_cls = folder_classification_service

    # ------------------------------------------------------------------ #
    def analyze(self, folder_path: str, recursive: bool = True) -> FolderIntelligenceInfo:
        """Compute statistics for a folder (prefix match over the index)."""
        folder_path = os.path.abspath(folder_path)
        prefix = folder_path if folder_path.endswith(os.sep) else folder_path + os.sep

        info = FolderIntelligenceInfo(folder_path=folder_path)

        try:
            from services.sqlite_indexer import IndexedFile
            from database.models import AIAnalysis

            with self._session_factory() as session:
                rows = session.query(IndexedFile).all()
                files_under = []
                for r in rows:
                    p = r.absolute_path or ""
                    if p == folder_path or p.startswith(prefix):
                        files_under.append(r)
                if not files_under:
                    return info

                info.total_files = len(files_under)
                info.total_size = sum(r.size or 0 for r in files_under)

                # Extension + modality distribution
                for r in files_under:
                    ext = (r.extension or os.path.splitext(r.filename or "")[1]).lower()
                    info.extension_distribution[ext] = (
                        info.extension_distribution.get(ext, 0) + 1
                    )
                    modality = _MODALITY_BY_EXT.get(ext, "document")
                    info.file_type_distribution[modality] = (
                        info.file_type_distribution.get(modality, 0) + 1
                    )

                # Date range from filesystem dates (clearly labelled)
                dates = [
                    (r.modified_date, r.absolute_path)
                    for r in files_under if r.modified_date
                ]
                if dates:
                    info.newest_file = max(dates, key=lambda d: d[0])[1]
                    info.oldest_file = min(dates, key=lambda d: d[0])[1]
                    info.date_range = (
                        f"{min(d for d, _ in dates).date()} → "
                        f"{max(d for d, _ in dates).date()}"
                    )

                # Category distribution + keywords via AI analysis (hash-keyed)
                hash_by_path = {
                    r.absolute_path: r.checksum for r in files_under
                    if r.checksum and len(r.checksum) == 64
                }
                checksums = list(set(hash_by_path.values()))
                cats = {}
                keywords: Dict[str, int] = {}
                if checksums:
                    ai_rows = (
                        session.query(AIAnalysis)
                        .filter(AIAnalysis.file_hash.in_(checksums))
                        .all()
                    )
                    for row in ai_rows:
                        cat = row.normalized_category or row.category
                        if cat:
                            cats[cat] = cats.get(cat, 0) + 1
                        for kw in self._extract_keywords(row):
                            keywords[kw] = keywords.get(kw, 0) + 1

                info.category_distribution = cats
                if cats:
                    info.dominant_category = max(cats, key=lambda k: cats[k])
                classified_hashes = {
                    row.file_hash for row in (session.query(AIAnalysis)
                                              .filter(AIAnalysis.file_hash.in_(checksums))
                                              .all())
                }
                info.classified_count = sum(
                    1 for h in hash_by_path.values() if h in classified_hashes
                )
                info.unclassified_count = max(0, info.total_files - info.classified_count)
                info.top_keywords = [
                    kw for kw, _ in sorted(keywords.items(), key=lambda kv: kv[1], reverse=True)
                ][:12]
            return info
        except Exception as exc:
            logger.error("Folder intelligence failed for %s: %s", folder_path, exc)
            return info

    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_keywords(row) -> List[str]:
        words: List[str] = []
        if row.summary:
            words.extend(row.summary.split()[:12])
        if row.keywords:
            try:
                data = json.loads(row.keywords)
                if isinstance(data, list):
                    words.extend(str(k) for k in data[:8])
            except (json.JSONDecodeError, TypeError):
                pass
        # crude stop-word filtering
        stop = {
            "the", "and", "for", "with", "that", "this", "are", "was",
            "from", "document", "file", "files", "a", "an", "of", "to",
            "in", "is", "on", "as", "by", "at", "be", "it", "or", "not",
            "but", "we", "you", "your", "our", "they", "them", "their",
        }
        out = []
        for w in words:
            w = w.strip(".,;:()[]\"'").lower()
            if len(w) >= 4 and w not in stop and w not in out:
                out.append(w)
        return out[:8]
