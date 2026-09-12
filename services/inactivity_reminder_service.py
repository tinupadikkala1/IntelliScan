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
from typing import Any, Dict, List, Optional

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

    def __init__(self, session_factory, classifier=None, days_threshold: int = 14) -> None:
        self._session_factory = session_factory
        self._classifier = classifier
        self.days_threshold = days_threshold

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
        self,
        threshold_days: Optional[int] = None,
        days: Optional[int] = None,
        max_results: int = 100,
        include_size: bool = True,
        watched_folder: Optional[str] = None,
    ) -> List[InactiveFileInfo]:
        """Find indexed files that have not been opened for >= threshold_days.

        Args:
            threshold_days: Number of days of inactivity (e.g. 7, 14, 28).
            days: Alias for threshold_days (for Phase 2.2 compatibility).
            max_results: Cap on total inactive files returned.
            include_size: Whether to include file size info.
            watched_folder: When set, only files inside this folder (and its
                subfolders) are checked. When None or empty, all indexed files
                are scanned (manual "Check Inactive Files" from the menu).

        Returns:
            List of InactiveFileInfo objects sorted by days_inactive descending.
        """
        eff_days = threshold_days if threshold_days is not None else days
        if eff_days is None:
            eff_days = getattr(self, "days_threshold", 14)

        if self._session_factory is None or eff_days <= 0:
            return []

        # Normalise the watched folder path once
        watch_abs = os.path.abspath(watched_folder) if watched_folder else None

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

                # Folder-scope filter: skip files outside the watched folder
                if watch_abs:
                    abs_path = os.path.abspath(path)
                    if not (abs_path.startswith(watch_abs + os.sep) or abs_path == watch_abs):
                        continue

                # Determine the reference access timestamp
                ref_dt = row.last_opened_at or row.scan_timestamp or row.created_date or row.modified_date
                if not ref_dt:
                    continue

                delta_days = (now - ref_dt).days
                if delta_days >= eff_days:
                    intro_str = (row.scan_timestamp or row.created_date or ref_dt).strftime("%Y-%m-%d")
                    opened_str = row.last_opened_at.strftime("%Y-%m-%d") if row.last_opened_at else "Never opened"

                    inactive_list.append(
                        InactiveFileInfo(
                            file_path=path,
                            file_name=os.path.basename(path),
                            days_inactive=delta_days,
                            introduced_date=intro_str,
                            last_opened=opened_str,
                            file_size=(row.size or 0) if include_size else 0,
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

    def reset_reminder_state(self) -> None:
        """Reset all inactivity reminder state for testing."""
        if hasattr(self, 'last_reminder_shown'):
            self.last_reminder_shown.clear()

        try:
            if self._session_factory:
                from database.models import InactivityReminder
                with self._session_factory() as session:
                    session.query(InactivityReminder).delete()
                    session.commit()
        except Exception as e:
            logger.debug(f"Could not clear DB reminders: {e}")

    def mark_file_accessed(self, file_path: str) -> None:
        """Mark a file as recently accessed, resetting its inactivity timer."""
        self.mark_file_opened(file_path)

    def get_inactive_stats(self, days: Optional[int] = None) -> Dict[str, Any]:
        """Get statistics about inactive files."""
        eff_days = days if days is not None else getattr(self, "days_threshold", 14)
        try:
            inactive_files = self.find_inactive_files(threshold_days=eff_days, max_results=1000)

            if not inactive_files:
                return {
                    'total_inactive': 0,
                    'total_size': 0,
                    'oldest_inactive': None,
                    'most_recent_inactive': None,
                    'average_days': 0,
                }

            total_size = sum(f.file_size for f in inactive_files)
            days_list = [f.days_inactive for f in inactive_files]

            return {
                'total_inactive': len(inactive_files),
                'total_size': total_size,
                'oldest_inactive': max(days_list) if days_list else 0,
                'most_recent_inactive': min(days_list) if days_list else 0,
                'average_days': sum(days_list) / len(days_list) if days_list else 0,
            }

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}
