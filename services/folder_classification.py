"""AI folder classification — B6-02 (#16).

Aggregates *existing* per-file classifications into a folder-level summary:

    folder
      ↓ indexed files under the folder (recursive prefix match)
      ↓ existing ai_analysis.normalized_category (per content hash)
      ↓ deterministic extension fallback for unclassified files
      ↓ aggregate distribution + dominant category
      ↓ persist to folder_classifications (upsert by folder_path)

No LLM is called per file (B6 §7.3). Data is recomputed from the current
index on each classify call, so added/removed/reclassified files are always
reflected; the persisted row is a cache for display/dashboard.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from engines.config import FOLDER_CLASSIFICATION_VERSION

logger = logging.getLogger(__name__)


@dataclass
class FolderClassificationInfo:
    """Folder-level category composition (B6-02)."""

    folder_path: str
    dominant_category: str = "other"
    distribution: Dict[str, int] = field(default_factory=dict)
    classified_count: int = 0
    unclassified_count: int = 0
    total_files: int = 0
    classification_version: str = ""
    ai_classified_count: int = 0
    fallback_classified_count: int = 0
    unindexed_count: int = 0
    stale_count: int = 0

    def to_dict(self) -> dict:
        return {
            "folder_path": self.folder_path,
            "dominant_category": self.dominant_category,
            "distribution": self.distribution,
            "classified_count": self.classified_count,
            "unclassified_count": self.unclassified_count,
            "total_files": self.total_files,
            "classification_version": self.classification_version,
            "ai_classified_count": self.ai_classified_count,
            "fallback_classified_count": self.fallback_classified_count,
            "unindexed_count": self.unindexed_count,
            "stale_count": self.stale_count,
        }


class FolderClassificationService:
    """Computes and persists folder-level classification summaries."""

    def __init__(
        self,
        session_factory,
        classifier=None,
        version: str = FOLDER_CLASSIFICATION_VERSION,
        recursive: bool = True,
    ) -> None:
        """Args:
            session_factory: DB session factory.
            classifier: ClassificationEngine (used for the deterministic
                extension fallback via category_from_extension).
            version: classification version recorded on the summary.
            recursive: include nested subfolders when aggregating.
        """
        self._session_factory = session_factory
        self._classifier = classifier
        self._version = version
        self._recursive = recursive

    # ------------------------------------------------------------------ #
    def classify_folder(self, folder_path: str) -> FolderClassificationInfo:
        """Aggregate file classifications under a folder and persist the result."""
        folder_path = os.path.abspath(folder_path)
        info = self._aggregate(folder_path)
        self._persist(folder_path, info)
        return info

    def _aggregate(self, folder_path: str) -> FolderClassificationInfo:
        """Compute the composition from indexed_files + ai_analysis."""
        try:
            from database.models import AIAnalysis
            from services.folder_snapshot import FolderSnapshotService

            distribution: Dict[str, int] = {}
            classified = 0
            unclassified = 0
            ai_classified = 0
            fallback_classified = 0

            with self._session_factory() as session:
                snapshot = FolderSnapshotService(self._session_factory).snapshot(
                    folder_path, recursive=self._recursive
                )
                entries = snapshot.file_entries
                # Preserve indexed metadata for callers/tests that inspect a
                # previously indexed path after its folder is unavailable.
                if not entries and not os.path.isdir(folder_path):
                    entries = snapshot.stale_entries
                if not entries:
                    return FolderClassificationInfo(
                        folder_path=folder_path,
                        distribution={},
                        classification_version=self._version,
                        stale_count=len(snapshot.stale_entries),
                    )

                cats_by_hash: Dict[str, str] = {}
                checksums = [entry.checksum for entry in entries if entry.checksum]
                if checksums:
                    cats = (
                        session.query(AIAnalysis.normalized_category, AIAnalysis.file_hash)
                        .filter(
                            AIAnalysis.file_hash.in_(checksums),
                            AIAnalysis.normalized_category.isnot(None),
                        )
                        .all()
                    )
                    for cat, h in cats:
                        if cat:
                            cats_by_hash[h] = cat

            # Fall back to deterministic extension-based category for any
            # file whose content hash has no normalized category.
            fallback_fn = None
            if self._classifier is not None:
                fallback_fn = getattr(self._classifier, "category_for_path", None)
            from services.classification_engine import category_from_extension

            for entry in entries:
                cat = cats_by_hash.get(entry.checksum or "", "")
                if cat:
                    ai_classified += 1
                elif fallback_fn is not None:
                    try:
                        cat = fallback_fn(entry.path)
                    except Exception:
                        cat = None
                if not cat:
                    cat = category_from_extension(entry.path) or "other"
                    fallback_classified += 1
                elif not cats_by_hash.get(entry.checksum or "", ""):
                    fallback_classified += 1
                distribution[cat] = distribution.get(cat, 0) + 1
                if cat and cat != "other":
                    classified += 1
                else:
                    unclassified += 1

            dominant = max(distribution, key=lambda k: distribution[k]) if distribution else "other"
            return FolderClassificationInfo(
                folder_path=folder_path,
                dominant_category=dominant,
                distribution=distribution,
                classified_count=classified,
                unclassified_count=unclassified,
                total_files=len(entries),
                classification_version=self._version,
                ai_classified_count=ai_classified,
                fallback_classified_count=fallback_classified,
                unindexed_count=sum(1 for e in entries if e.status == "unindexed"),
                stale_count=len(snapshot.stale_entries),
            )
        except Exception as exc:
            logger.error("Folder classification failed for %s: %s", folder_path, exc)
            return FolderClassificationInfo(
                folder_path=folder_path,
                distribution={},
                classification_version=self._version,
            )

    def _persist(self, folder_path: str, info: FolderClassificationInfo) -> None:
        try:
            from database.models import FolderClassification

            with self._session_factory() as session:
                row = (
                    session.query(FolderClassification)
                    .filter(FolderClassification.folder_path == folder_path)
                    .first()
                )
                if row is None:
                    row = FolderClassification(folder_path=folder_path)
                    session.add(row)
                row.dominant_category = info.dominant_category
                row.distribution_json = json.dumps(info.distribution)
                row.classified_count = info.classified_count
                row.unclassified_count = info.unclassified_count
                row.classification_version = info.classification_version
                row.generated_at = datetime.now()
                row.updated_at = datetime.now()
                session.commit()
        except Exception as exc:
            logger.error("Failed to persist folder classification %s: %s", folder_path, exc)

    # ------------------------------------------------------------------ #
    def get(self, folder_path: str) -> Optional[FolderClassificationInfo]:
        """Read a persisted folder summary (None when never computed)."""
        try:
            from database.models import FolderClassification

            with self._session_factory() as session:
                row = (
                    session.query(FolderClassification)
                    .filter(FolderClassification.folder_path == folder_path)
                    .first()
                )
                if row is None:
                    return None
                distribution = {}
                if row.distribution_json:
                    try:
                        distribution = json.loads(row.distribution_json) or {}
                    except (json.JSONDecodeError, TypeError):
                        distribution = {}
                return FolderClassificationInfo(
                    folder_path=row.folder_path,
                    dominant_category=row.dominant_category,
                    distribution=distribution,
                    classified_count=row.classified_count,
                    unclassified_count=row.unclassified_count,
                    total_files=(row.classified_count or 0) + (row.unclassified_count or 0),
                    classification_version=row.classification_version or "",
                )
        except Exception as exc:
            logger.debug("Failed to load folder classification %s: %s", folder_path, exc)
            return None

    def stats(self) -> dict:
        """Dashboard helper: number of classified folders."""
        try:
            from database.models import FolderClassification

            with self._session_factory() as session:
                return {"classified_folders": session.query(FolderClassification).count()}
        except Exception:
            return {"classified_folders": 0}
