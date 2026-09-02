"""Metadata editor service — B7-6 (#23).

Allows manual editing of *user-facing* metadata (title, description, notes,
user tags, custom key/values) while keeping AI-generated metadata fully
separate. User edits live in ``indexed_files.user_metadata_json``; AI values
(summary/category/tags/language) are never overwritten by this service.

Editing preserves SHA-256, evidence, embeddings and all derived layers —
only the user-metadata blob changes.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

SUPPORTED_FIELDS = ["title", "description", "notes", "user_tags", "custom"]

_USER_TAG_MAX = 20
_USER_TAG_MIN_LEN = 1


class MetadataEditorError(Exception):
    """Raised when a metadata write cannot be completed."""


class MetadataEditorService:
    """Read/write user-edited metadata for indexed files."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------ #
    def get(self, file_path: str) -> dict:
        """Read the user-metadata dict for a file (empty dict when none)."""
        row = self._row(file_path)
        if row is None or not row.user_metadata_json:
            return {}
        try:
            data = json.loads(row.user_metadata_json) or {}
            if not isinstance(data, dict):
                return {}
            return data
        except (json.JSONDecodeError, TypeError):
            return {}

    def save(self, file_path: str, updates: dict) -> dict:
        """Merge ``updates`` into user metadata and persist.

        Supported keys (others are ignored): title, description, notes,
        user_tags (list of str), custom (dict). Returns the saved dict.
        """
        if not file_path:
            raise MetadataEditorError("No file path given")
        current = self.get(file_path)

        allowed = {k: v for k, v in (updates or {}).items() if k in SUPPORTED_FIELDS}
        for key, value in allowed.items():
            if key == "user_tags":
                value = self._validate_tags(value)
            elif key == "custom":
                value = self._validate_custom(value)
            else:
                value = self._validate_text(value, key)
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value

        with self._session_factory() as session:
            from services.sqlite_indexer import IndexedFile
            db_row = session.query(IndexedFile).filter_by(absolute_path=file_path).first()
            if db_row is None:
                raise MetadataEditorError(f"File is not indexed: {file_path}")
            db_row.user_metadata_json = json.dumps(current, ensure_ascii=False)
            from datetime import datetime
            db_row.last_updated = datetime.now()
            session.commit()
        return current

    def clear(self, file_path: str) -> None:
        """Remove all user-edited metadata for a file."""
        with self._session_factory() as session:
            from services.sqlite_indexer import IndexedFile
            db_row = session.query(IndexedFile).filter_by(absolute_path=file_path).first()
            if db_row is not None:
                db_row.user_metadata_json = None
                session.commit()

    # ------------------------------------------------------------------ #
    def has_user_metadata(self, file_path: str) -> bool:
        return bool(self.get(file_path))

    def all_custom_keys(self) -> List[str]:
        """Distinct custom keys across the index (for editors/filters)."""
        keys = set()
        try:
            from services.sqlite_indexer import IndexedFile
            with self._session_factory() as session:
                for row in session.query(IndexedFile).all():
                    if not row.user_metadata_json:
                        continue
                    try:
                        data = json.loads(row.user_metadata_json) or {}
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(data.get("custom"), dict):
                        keys.update(data["custom"].keys())
        except Exception as exc:
            logger.debug("custom keys scan failed: %s", exc)
        return sorted(keys)

    # ------------------------------------------------------------------ #
    def _row(self, file_path: str):
        try:
            from services.sqlite_indexer import IndexedFile
            with self._session_factory() as session:
                return session.query(IndexedFile).filter_by(
                    absolute_path=os_abspath(file_path)
                ).first()
        except Exception as exc:
            logger.debug("metadata row lookup failed: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate_text(value, key: str) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if len(text) > 2000:
            raise MetadataEditorError(f"'{key}' is too long (max 2000 chars)")
        return text or None

    @staticmethod
    def _validate_tags(value) -> Optional[List[str]]:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            tags = [t.strip() for t in value.split(",")]
        else:
            tags = [str(t).strip() for t in value]
        tags = [t for t in tags if t]
        if len(tags) > _USER_TAG_MAX:
            raise MetadataEditorError(f"Too many user tags (max {_USER_TAG_MAX})")
        for t in tags:
            if len(t) < _USER_TAG_MIN_LEN or len(t) > 60:
                raise MetadataEditorError(
                    f"User tag '{t}' must be 1..60 characters"
                )
        return tags or None

    @staticmethod
    def _validate_custom(value) -> Optional[dict]:
        if value in (None, ""):
            return None
        if not isinstance(value, dict):
            raise MetadataEditorError("'custom' must be a JSON object")
        out = {}
        for k, v in value.items():
            key = str(k).strip()
            if not key:
                continue
            if len(key) > 80:
                raise MetadataEditorError(f"Custom key '{key}' too long")
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[key] = v
            else:
                out[key] = str(v)
        return out or None


def os_abspath(path: str) -> str:
    import os
    return os.path.abspath(path)
