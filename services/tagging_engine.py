"""Auto-tagging engine — B5-02.

Generates consistent, canonical semantic tags per file by normalizing the
free-form tags produced during AI analysis. Each canonical tag is:

    canonical form   — ``machine-learning`` (lowercase, hyphenated)
    display name     — ``Machine Learning`` (for chips/UI)
    normalized form  — used for dedup + search

Normalization folds case, punctuation and common separator variants so
``Machine Learning``, ``machine-learning`` and ``machine_learning`` resolve
to one tag — without aggressive fuzzy merging that could destroy meaning.
Tags are persisted on the ``ai_analysis`` row (``normalized_tags`` JSON +
``tagging_version``) so they survive renames/moves (identity is content hash).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import List, Optional

from engines.config import TAG_MAX_COUNT, TAG_MIN_LENGTH, TAGGING_VERSION

logger = logging.getLogger(__name__)

_SEPARATOR_RE = re.compile(r"[\s_]+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def canonical_tag(value: str) -> str:
    """Normalize a tag to its canonical (dedup) form.

    Folds case, collapses whitespace/underscores to hyphens, strips
    punctuation. Empty results are dropped by callers.
    """
    if not value:
        return ""
    text = value.strip().lower()
    text = _NON_ALNUM_RE.sub("-", text)
    text = _SEPARATOR_RE.sub("-", text)
    text = text.strip("-")
    return text


def display_tag(canonical: str) -> str:
    """Human-friendly title case for chip display."""
    if not canonical:
        return ""
    return canonical.replace("-", " ").title()


def normalize_tags(tags: List[str]) -> List[str]:
    """Deduplicate + canonicalize a raw tag list, bounded and filtered.

    Returns canonical tags (deduped, order-preserving). Tags shorter than
    TAG_MIN_LENGTH or purely punctuation are dropped.
    """
    seen: List[str] = []
    for t in tags or []:
        canon = canonical_tag(t)
        if not canon or len(canon) < TAG_MIN_LENGTH:
            continue
        if canon not in seen:
            seen.append(canon)
        if len(seen) >= TAG_MAX_COUNT:
            break
    return seen


class TaggingEngine:
    """Generates and persists canonical tags per file."""

    def __init__(
        self,
        session_factory,
        analysis_cache=None,
        ai_service=None,
        version: str = TAGGING_VERSION,
        max_tags: int = TAG_MAX_COUNT,
    ) -> None:
        self._session_factory = session_factory
        self._cache = analysis_cache
        self._ai_service = ai_service
        self._version = version
        self._max_tags = max_tags

    # ------------------------------------------------------------------ #
    def generate_tags(self, file_path: str) -> List[str]:
        """Generate + persist canonical tags for one file; returns them."""
        file_path = os.path.abspath(file_path)
        raw = self._raw_tags(file_path)
        tags = normalize_tags(raw)[: self._max_tags]
        self._persist(file_path, tags)
        return tags

    def _raw_tags(self, file_path: str) -> List[str]:
        """Collect candidate tags: AI tags, keywords, filename tokens."""
        candidates: List[str] = []

        analysis = self._get_analysis(file_path)
        if analysis is not None:
            candidates.extend(analysis.get("tags") or [])
            candidates.extend(analysis.get("keywords") or [])

        # Filename stem is a weak but useful signal (e.g. "ml_notes").
        stem = os.path.splitext(os.path.basename(file_path))[0]
        stem = re.sub(r"[\s_]+", " ", stem).strip()
        if stem and len(stem) >= TAG_MIN_LENGTH:
            candidates.append(stem)

        return candidates

    def _get_analysis(self, file_path: str) -> Optional[dict]:
        if self._cache is None:
            return None
        from services.file_identity import calculate_sha256_safe

        file_hash = calculate_sha256_safe(file_path)
        if not file_hash:
            return None
        analysis = self._cache.get_analysis(file_hash)
        if analysis is not None:
            return analysis
        if self._ai_service is None:
            return None
        try:
            from ai.analysis_manager import AnalysisManager

            manager = AnalysisManager(self._ai_service)
            result = manager.analyze_file(file_path)
            return None if "error" in result else result
        except Exception as exc:
            logger.debug("AI analysis generation failed for %s: %s", file_path, exc)
            return None

    def _persist(self, file_path: str, tags: List[str]) -> None:
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
                    row = AIAnalysis(
                        file_hash=file_hash,
                        normalized_tags=json.dumps(tags),
                        tagging_version=self._version,
                        tagged_at=datetime.now(),
                    )
                    session.add(row)
                else:
                    row.normalized_tags = json.dumps(tags)
                    row.tagging_version = self._version
                    row.tagged_at = datetime.now()
                session.commit()
        except Exception as exc:
            logger.error("Failed to persist tags for %s: %s", file_path, exc)

    # ------------------------------------------------------------------ #
    def tags_for_path(self, file_path: str) -> List[str]:
        """Read persisted canonical tags for a path (may be empty)."""
        try:
            from services.file_identity import calculate_sha256_safe

            file_hash = calculate_sha256_safe(file_path)
            if not file_hash:
                return []
            from database.models import AIAnalysis

            with self._session_factory() as session:
                row = (
                    session.query(AIAnalysis)
                    .filter(AIAnalysis.file_hash == file_hash)
                    .first()
                )
                if row is None or not row.normalized_tags:
                    return []
                return json.loads(row.normalized_tags) or []
        except Exception:
            return []

    def add_tag(self, file_path: str, tag: str) -> List[str]:
        """Manually add a tag (no automatic destructive deletion)."""
        canon = canonical_tag(tag)
        tags = self.tags_for_path(file_path)
        if canon and canon not in tags:
            tags.append(canon)
            self._persist(file_path, tags)
        return tags

    def remove_tag(self, file_path: str, tag: str) -> List[str]:
        """Manually remove a specific tag."""
        canon = canonical_tag(tag)
        tags = self.tags_for_path(file_path)
        if canon in tags:
            tags = [t for t in tags if t != canon]
            self._persist(file_path, tags)
        return tags

    def rename_tag(self, file_path: str, old: str, new: str) -> List[str]:
        """Rename/merge a tag (both forms normalized)."""
        old_c = canonical_tag(old)
        new_c = canonical_tag(new)
        tags = self.tags_for_path(file_path)
        if old_c in tags and new_c:
            tags = [new_c if t == old_c else t for t in tags]
            tags = list(dict.fromkeys(tags))  # dedupe after merge
            self._persist(file_path, tags)
        return tags

    # ------------------------------------------------------------------ #
    def tag_batch(
        self,
        paths: List[str],
        progress_callback=None,
        cancel_event=None,
    ) -> dict:
        """Tag many files with progress + cancellation."""
        tagged = skipped = errors = 0
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
                tags = self.generate_tags(path)
                if tags:
                    tagged += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                logger.debug("Tagging failed for %s: %s", path, exc)
        return {"tagged": tagged, "skipped": skipped, "errors": errors}

    def is_current(self, file_path: str) -> bool:
        """True when the stored tags match the current tagging version."""
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
                    row and row.normalized_tags and row.tagging_version == self._version
                )
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    def tags_in_workspace(self, limit: int = 30) -> List[dict]:
        """Dashboard helper: [{"tag": canonical, "count": n}] most frequent."""
        try:
            from services.sqlite_indexer import IndexedFile

            with self._session_factory() as session:
                rows = session.query(IndexedFile.checksum).all()
                hashes = {r[0] for r in rows if r[0]}
            if not hashes:
                return []
            from database.models import AIAnalysis

            with self._session_factory() as session:
                tagged = (
                    session.query(AIAnalysis.normalized_tags)
                    .filter(
                        AIAnalysis.normalized_tags.isnot(None),
                        AIAnalysis.file_hash.in_(hashes),
                    )
                    .all()
                )
            counts: dict = {}
            for (blob,) in tagged:
                try:
                    tags = json.loads(blob) or []
                except (json.JSONDecodeError, TypeError):
                    continue
                for t in tags:
                    counts[t] = counts.get(t, 0) + 1
            ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
            return [{"tag": t, "count": c} for t, c in ranked[:limit]]
        except Exception as exc:
            logger.debug("Workspace tags failed: %s", exc)
            return []
