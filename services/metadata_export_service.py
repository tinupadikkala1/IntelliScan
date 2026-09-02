"""Metadata export service — B7-3 (#15).

Exports IntelliVault metadata for the workspace, current folder, or a
selection of files to JSON or CSV. Purely a read-side export: never
mutates the database or the filesystem.

Fields exported are the stable, user-facing index/AI metadata; private
internal fields (extracted_text blobs, internal ids) are excluded.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

EXPORT_FIELDS = [
    "path",
    "filename",
    "extension",
    "mime_type",
    "size",
    "created_date",
    "modified_date",
    "checksum",
    "language",
    "category",
    "tags",
    "summary",
    "caption",
    "quality_score",
    "objects",
]


class MetadataExportError(Exception):
    """Raised when an export cannot be produced."""


def _load_ai(ai_rows, hash_by_path: dict) -> dict:
    """Build path -> AI metadata map from ai_analysis rows (hash-keyed)."""
    out: dict = {}
    for row in ai_rows:
        for path, h in hash_by_path.items():
            if h and h == row.file_hash:
                out[path] = row
                break
    return out


def _row_to_record(path: str, indexed, ai) -> dict:
    rec = {
        "path": path,
        "filename": indexed.filename if indexed else os.path.basename(path),
        "extension": (indexed.extension if indexed else ""),
        "mime_type": (indexed.mime_type if indexed else ""),
        "size": (indexed.size if indexed else 0),
        "created_date": str(indexed.created_date)[:19] if indexed and indexed.created_date else "",
        "modified_date": str(indexed.modified_date)[:19] if indexed and indexed.modified_date else "",
        "checksum": (indexed.checksum if indexed else ""),
    }
    if ai is not None:
        rec["language"] = ai.language or ""
        rec["category"] = ai.normalized_category or ai.category or ""
        tags = ai.normalized_tags or ai.tags or ""
        rec["tags"] = tags
        rec["summary"] = (ai.summary or "")[:500]
        rec["caption"] = ai.caption or ""
        rec["quality_score"] = ai.quality_score
        objects = ai.objects_json or "[]"
        try:
            objs = json.loads(objects)
            rec["objects"] = json.dumps([o.get("label", "") for o in objs])
        except (json.JSONDecodeError, TypeError):
            rec["objects"] = ""
    else:
        rec.update({
            "language": "", "category": "", "tags": "", "summary": "",
            "caption": "", "quality_score": None, "objects": "",
        })
    return rec


class MetadataExportService:
    """Produces JSON/CSV exports of indexed file metadata."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------ #
    def collect(
        self,
        scope: str = "workspace",
        folder: Optional[str] = None,
        files: Optional[List[str]] = None,
    ) -> List[dict]:
        """Collect export records for a scope.

        Args:
            scope: 'workspace' | 'folder' | 'files'.
            folder: absolute folder path (scope='folder').
            files: list of absolute paths (scope='files').

        Returns:
            List of record dicts (one per file), sorted by path.
        """
        try:
            from services.sqlite_indexer import IndexedFile
            from database.models import AIAnalysis

            with self._session_factory() as session:
                indexed_by_path = {}
                for r in session.query(IndexedFile).all():
                    indexed_by_path[r.absolute_path] = r

                if scope == "files" and files:
                    paths = [os.path.abspath(p) for p in files if os.path.isfile(p)]
                elif scope == "folder" and folder:
                    prefix = folder if folder.endswith(os.sep) else folder + os.sep
                    paths = [
                        p for p in indexed_by_path
                        if p == folder or p.startswith(prefix)
                    ]
                else:
                    paths = list(indexed_by_path.keys())

                paths = sorted(paths)

                hash_by_path = {
                    p: r.checksum for p, r in indexed_by_path.items()
                    if r.checksum and len(r.checksum) == 64
                }
                ai_rows = list(session.query(AIAnalysis).all())
                ai_by_path = _load_ai(ai_rows, hash_by_path)

                return [
                    _row_to_record(p, indexed_by_path.get(p), ai_by_path.get(p))
                    for p in paths
                ]
        except Exception as exc:
            logger.error("Metadata export collection failed: %s", exc)
            raise MetadataExportError(f"Could not collect metadata: {exc}") from exc

    # ------------------------------------------------------------------ #
    def to_json(self, records: List[dict]) -> str:
        """Serialize records to pretty JSON (UTF-8)."""
        payload = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(records),
            "files": records,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def to_csv(self, records: List[dict]) -> str:
        """Serialize records to CSV (UTF-8, stable column order)."""
        if not records:
            return ""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow({k: rec.get(k, "") for k in EXPORT_FIELDS})
        return buf.getvalue()

    # ------------------------------------------------------------------ #
    def export(
        self,
        destination: str,
        fmt: str = "json",
        scope: str = "workspace",
        folder: Optional[str] = None,
        files: Optional[List[str]] = None,
    ) -> dict:
        """Collect and write an export to ``destination``.

        Args:
            destination: output file path.
            fmt: 'json' | 'csv'.
            scope, folder, files: collect() arguments.

        Returns:
            {"path", "format", "count", "bytes"}
        """
        fmt = (fmt or "json").lower().strip(".")
        if fmt not in ("json", "csv"):
            raise MetadataExportError(f"Unsupported export format: {fmt}")

        records = self.collect(scope=scope, folder=folder, files=files)
        body = self.to_json(records) if fmt == "json" else self.to_csv(records)

        dest_dir = os.path.dirname(os.path.abspath(destination))
        if dest_dir and not os.path.isdir(dest_dir):
            raise MetadataExportError(f"Destination directory does not exist: {dest_dir}")
        try:
            with open(destination, "w", encoding="utf-8") as fh:
                fh.write(body)
        except OSError as exc:
            raise MetadataExportError(f"Cannot write export: {exc}") from exc

        return {
            "path": destination,
            "format": fmt,
            "count": len(records),
            "bytes": len(body.encode("utf-8")),
        }
