"""File timeline service — B7-7 (#26).

Provides a chronological view of file activity derived from data that is
already recorded — it never fabricates events. Sources:

  - ``indexed_files`` created/modified dates (filesystem provenance, labelled
    "created" / "modified")
  - ``recent`` opens (recorded IntelliVault events, labelled "opened")
  - ``tasks`` indexing activity (labelled "indexed", best-effort)

Events are grouped by day and filterable by folder, file type and event kind.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

EVENT_KINDS = ("created", "modified", "opened")


class TimelineService:
    """Read-side service for the file timeline."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------ #
    def events(
        self,
        days: int = 90,
        folder: Optional[str] = None,
        extension: Optional[str] = None,
        kinds: Optional[List[str]] = None,
        limit: int = 500,
    ) -> List[dict]:
        """Return timeline events (newest first).

        Args:
            days: include events from the last N days.
            folder: restrict to files under this folder (prefix match).
            extension: restrict to files with this extension ('' = no ext).
            kinds: subset of ('created','modified','opened','indexed').
            limit: maximum number of events.

        Returns:
            List of {"kind","path","filename","time","day"} dicts.
        """
        kinds = kinds or list(EVENT_KINDS)
        since = datetime.now() - timedelta(days=days)
        events: List[dict] = []
        seen = set()

        def _push(kind: str, path: str, when) -> None:
            if not path or when is None:
                return
            if isinstance(when, str):
                try:
                    when = datetime.fromisoformat(when)
                except ValueError:
                    return
            if when < since:
                return
            if folder and not (path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)):
                return
            ext = os.path.splitext(path)[1].lower()
            if extension is not None and ext != extension:
                return
            key = (kind, path, when.isoformat(timespec="seconds"))
            if key in seen:
                return
            seen.add(key)
            events.append({
                "kind": kind,
                "path": path,
                "filename": os.path.basename(path),
                "time": when,
                "day": when.date().isoformat(),
                "extension": ext,
            })

        try:
            from services.sqlite_indexer import IndexedFile
            from database.models import Recent

            with self._session_factory() as session:
                if "created" in kinds:
                    for r in session.query(IndexedFile).all():
                        _push("created", r.absolute_path, r.created_date)
                if "modified" in kinds:
                    for r in session.query(IndexedFile).all():
                        if r.modified_date and r.created_date:
                            try:
                                diff = (r.modified_date - r.created_date).total_seconds()
                                if abs(diff) <= 5:
                                    continue  # Skip false modified event for files never edited after creation
                            except Exception:
                                pass
                        _push("modified", r.absolute_path, r.modified_date)
                if "opened" in kinds:
                    for r in session.query(Recent).all():
                        _push("opened", r.path, r.opened)
        except Exception as exc:
            logger.debug("timeline events failed: %s", exc)

        events.sort(key=lambda e: e["time"], reverse=True)
        out = events[:limit]
        for e in out:
            e["time"] = e["time"].isoformat(timespec="seconds")
        return out

    # ------------------------------------------------------------------ #
    def grouped(self, **kwargs) -> List[dict]:
        """Events grouped by day, newest day first.

        Returns [{"day", "count", "events": [...]}].
        """
        events = self.events(**kwargs)
        groups: dict = {}
        for e in events:
            groups.setdefault(e["day"], []).append(e)
        return [
            {"day": day, "count": len(evs), "events": evs}
            for day, evs in sorted(groups.items(), reverse=True)
        ]

    # ------------------------------------------------------------------ #
    def export_timeline(self, events: List[dict], file_path: str) -> bool:
        """Export timeline activity to CSV or JSON file.

        Args:
            events: List of event dicts or grouped events.
            file_path: Output target path (.csv or .json).

        Returns:
            True if export succeeded.
        """
        if not file_path:
            return False

        ext = os.path.splitext(file_path)[1].lower()

        flat_events = []
        for item in events:
            if isinstance(item, dict) and "events" in item:
                flat_events.extend(item["events"])
            elif isinstance(item, dict):
                flat_events.append(item)

        if ext == ".json":
            import json
            data = [
                {
                    "event_kind": e.get("kind"),
                    "timestamp": str(e.get("time")),
                    "day": e.get("day"),
                    "filename": e.get("filename"),
                    "path": e.get("path"),
                    "extension": e.get("extension"),
                }
                for e in flat_events
            ]
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        else:
            import csv
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Event Kind", "Date & Time", "Day", "Filename", "File Path", "Extension"])
                for e in flat_events:
                    writer.writerow([
                        e.get("kind", ""),
                        str(e.get("time", "")),
                        e.get("day", ""),
                        e.get("filename", ""),
                        e.get("path", ""),
                        e.get("extension", ""),
                    ])
            return True

    # ------------------------------------------------------------------ #
    def stats(self, days: int = 90) -> dict:
        """Lightweight aggregates for the timeline header."""
        events = self.events(days=days, limit=100000)
        by_kind = {}
        by_ext = {}
        for e in events:
            by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
            ext = e.get("extension") or "(none)"
            by_ext[ext] = by_ext.get(ext, 0) + 1
        return {
            "total": len(events),
            "by_kind": by_kind,
            "by_extension": by_ext,
        }
