"""Inactivity Reminder Service — Track file access and alert users about stale/unopened files.

Monitors indexed files and flags documents that have not been opened for a user-configured
threshold (e.g. 7, 14, 28 days). Calculates inactivity based on the latest of:
  - last_opened_at (recorded when user opens file in IntelliScan)
  - scan_timestamp (date file was introduced into IntelliScan)
  - created_date / modified_date (disk timestamp)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class InactiveFileInfo:
    """Represents a file that has remained inactive past the threshold."""

    file_path: str
    file_name: str
    days_inactive: int
    introduced_date: str  # Formatted scan_timestamp or created_date
    last_opened: str      # Formatted last_opened_at or "Never"
    file_size: int
    category: str = "general"

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "file_name": self.file_name,
            "days_inactive": self.days_inactive,
            "introduced_date": self.introduced_date,
            "last_opened": self.last_opened,
            "file_size": self.file_size,
            "category": self.category,
        }


class InactivityReminderService:
    """Service to scan for inactive/unopened files and record file access events."""

    def __init__(self, session_factory, classifier=None) -> None:
        self._session_factory = session_factory
        self._classifier = classifier

    def mark_file_opened(self, file_path: str) -> None:
        """Record current time as last_opened_at for the file in SQLite."""
        if self._session_factory is None or not file_path:
            return
        abs_path = os.path.abspath(file_path)
        now = datetime.utcnow()

        try:
            from services.sqlite_indexer import IndexedFile
            with self._session_factory() as session:
                row = session.query(IndexedFile).filter(IndexedFile.absolute_path == abs_path).first()
                if row:
                    row.last_opened_at = now
                    session.commit()
                    logger.debug("Marked file as opened: %s", abs_path)
        except Exception as exc:
            logger.debug("Failed to record file open for %s: %s", abs_path, exc)

    def find_inactive_files(
        self, threshold_days: int = 14, max_results: int = 50
    ) -> List[InactiveFileInfo]:
        """Find indexed files that have not been opened for >= threshold_days.

        Args:
            threshold_days: Number of days of inactivity (e.g. 7, 14, 28).
            max_results: Cap on total inactive files returned.

        Returns:
            List of InactiveFileInfo objects sorted by days_inactive descending.
        """
        if self._session_factory is None or threshold_days <= 0:
            return []

        now = datetime.utcnow()
        inactive_list: List[InactiveFileInfo] = []

        try:
            from services.sqlite_indexer import IndexedFile
            with self._session_factory() as session:
                rows = session.query(IndexedFile).all()

            for row in rows:
                path = row.absolute_path
                if not path or not os.path.isfile(path):
                    continue

                # Determine the reference access timestamp
                ref_dt = row.last_opened_at or row.scan_timestamp or row.created_date or row.modified_date
                if not ref_dt:
                    continue

                delta_days = (now - ref_dt).days
                if delta_days >= threshold_days:
                    intro_str = (row.scan_timestamp or row.created_date or ref_dt).strftime("%Y-%m-%d")
                    opened_str = row.last_opened_at.strftime("%Y-%m-%d") if row.last_opened_at else "Never opened"

                    inactive_list.append(
                        InactiveFileInfo(
                            file_path=path,
                            file_name=os.path.basename(path),
                            days_inactive=delta_days,
                            introduced_date=intro_str,
                            last_opened=opened_str,
                            file_size=row.size or 0,
                            category="general",
                        )
                    )

        except Exception as exc:
            logger.error("Failed to query inactive files: %s", exc)

        inactive_list.sort(key=lambda item: item.days_inactive, reverse=True)
        top_results = inactive_list[:max_results]

        if self._classifier is not None:
            for item in top_results:
                try:
                    item.category = self._classifier.category_for_path(item.file_path) or "general"
                except Exception:
                    pass

        return top_results

