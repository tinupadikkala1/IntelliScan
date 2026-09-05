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
import os
import uuid
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from engines.evidence_engine import EvidenceChunk

logger = logging.getLogger(__name__)

SUPPORTED_FIELDS = ["title", "description", "notes", "user_tags", "custom"]

_USER_TAG_MAX = 20
_USER_TAG_MIN_LEN = 1


def build_user_metadata_chunk(
    file_path: str,
    user_metadata: dict,
    file_hash: str = "",
) -> Optional[EvidenceChunk]:
    """Build an EvidenceChunk representing user-edited metadata for search & AI context."""
    if not user_metadata or not isinstance(user_metadata, dict):
        return None

    lines: List[str] = []
    if user_metadata.get("title"):
        lines.append(f"Title: {user_metadata['title']}")
    if user_metadata.get("description"):
        lines.append(f"Description: {user_metadata['description']}")
    if user_metadata.get("notes"):
        lines.append(f"Notes: {user_metadata['notes']}")
    if user_metadata.get("user_tags"):
        tags = user_metadata["user_tags"]
        if isinstance(tags, list):
            lines.append(f"User Tags: {', '.join(str(t) for t in tags)}")
        else:
            lines.append(f"User Tags: {tags}")
    if user_metadata.get("custom"):
        try:
            lines.append(f"Custom Metadata: {json.dumps(user_metadata['custom'], ensure_ascii=False)}")
        except Exception:
            lines.append(f"Custom Metadata: {user_metadata['custom']}")

    if not lines:
        return None

    from engines.config import detect_modality_and_ext
    from engines.evidence_engine import EvidenceChunk

    abs_path = os.path.abspath(file_path)
    file_name = os.path.basename(abs_path)
    modality, _ = detect_modality_and_ext(abs_path)

    full_text = f"User Curated Metadata & Notes for {file_name} ({modality}):\n" + "\n".join(lines)
    chunk_id = uuid.uuid5(uuid.NAMESPACE_URL, f"user_meta:{abs_path}").hex

    return EvidenceChunk(
        chunk_id=chunk_id,
        text=full_text,
        file_path=abs_path,
        file_hash=file_hash or "",
        source_type="user_metadata",
        source_index=0,
        source_label=f"User Metadata: {file_name}",
        char_start=0,
        char_end=len(full_text),
        modality=modality,
        confidence=1.0,
        metadata={"is_user_metadata": True, **user_metadata},
    )


class MetadataEditorError(Exception):
    """Raised when a metadata write cannot be completed."""


class MetadataEditorService:
    """Read/write user-edited metadata for indexed files."""

    def __init__(
        self,
        session_factory,
        retrieval_engine=None,
        db_store=None,
    ) -> None:
        self._session_factory = session_factory
        self._retrieval_engine = retrieval_engine
        self._db_store = db_store

    def _sync_to_retrieval(self, file_path: str, user_metadata: dict, file_hash: str = "") -> None:
        """Synchronize user metadata chunk to in-memory retrieval, vector index, and persistence."""
        abs_path = os.path.abspath(file_path)
        chunk = build_user_metadata_chunk(abs_path, user_metadata, file_hash=file_hash)
        if not chunk:
            self._remove_from_retrieval(abs_path)
            return

        # 1. Update in-memory retrieval evidence store
        if self._retrieval_engine is not None:
            try:
                self._retrieval_engine._evidence[chunk.chunk_id] = chunk
            except Exception as exc:
                logger.debug("Failed updating retrieval evidence with user metadata: %s", exc)

            # 2. Add or update FAISS vector embedding
            try:
                emb = getattr(self._retrieval_engine, "_embedding", None)
                vec_engine = getattr(self._retrieval_engine, "_vector", None)
                if emb is not None and vec_engine is not None:
                    vecs = emb.embed_documents([chunk.text])
                    if vecs is not None and len(vecs) > 0:
                        vec_engine.remove_by_chunk_ids({chunk.chunk_id})
                        vec_engine.add(chunk.chunk_id, vecs[0])
            except Exception as exc:
                logger.debug("Live FAISS vector embedding for user metadata skipped/failed: %s", exc)

        # 3. Persist to DB store if available
        if self._db_store is not None:
            try:
                self._db_store.delete_evidence_by_chunk_ids({chunk.chunk_id})
                self._db_store.store_evidence([chunk])
                from engines.config import EMBEDDING_MODEL
                self._db_store.store_vector_maps(
                    [chunk.chunk_id], chunk.file_path, chunk.file_hash or file_hash or "", EMBEDDING_MODEL
                )
            except Exception as exc:
                logger.debug("Failed persisting user metadata evidence to DB store: %s", exc)

    def _remove_from_retrieval(self, file_path: str) -> None:
        """Remove user metadata chunk from retrieval evidence, FAISS, and persistence."""
        abs_path = os.path.abspath(file_path)
        chunk_id = uuid.uuid5(uuid.NAMESPACE_URL, f"user_meta:{abs_path}").hex

        if self._retrieval_engine is not None:
            try:
                self._retrieval_engine._evidence.pop(chunk_id, None)
            except Exception:
                pass
            try:
                vec_engine = getattr(self._retrieval_engine, "_vector", None)
                if vec_engine is not None:
                    vec_engine.remove_by_chunk_ids({chunk_id})
            except Exception:
                pass

        if self._db_store is not None:
            try:
                self._db_store.delete_evidence_by_chunk_ids({chunk_id})
            except Exception as exc:
                logger.debug("Failed deleting user metadata from DB store: %s", exc)

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

        file_hash = ""
        with self._session_factory() as session:
            from services.sqlite_indexer import IndexedFile
            db_row = session.query(IndexedFile).filter_by(absolute_path=file_path).first()
            if db_row is None:
                raise MetadataEditorError(f"File is not indexed: {file_path}")
            db_row.user_metadata_json = json.dumps(current, ensure_ascii=False)
            from datetime import datetime
            db_row.last_updated = datetime.now()
            file_hash = db_row.checksum or ""
            session.commit()

        self._sync_to_retrieval(file_path, current, file_hash=file_hash)
        return current

    def clear(self, file_path: str) -> None:
        """Remove all user-edited metadata for a file."""
        with self._session_factory() as session:
            from services.sqlite_indexer import IndexedFile
            db_row = session.query(IndexedFile).filter_by(absolute_path=file_path).first()
            if db_row is not None:
                db_row.user_metadata_json = None
                session.commit()

        self._remove_from_retrieval(file_path)

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
