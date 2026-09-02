"""Organization suggestion engine — B5-08 / B6-04 / B6-05.

Recommends logical organization *targets* for a file (collections first,
then existing indexed folders) and — since Batch 6 — safe duplicate-removal
recommendations.

Deterministic evidence precedes any LLM reasoning:

    selected file
     ↓
    related files (vector similarity)
     ↓
    dominant collections among related files
     ↓
    category / tags of the file
     ↓
    candidate targets (existing collections / folders only)
     ↓
    score candidates
     ↓
    optional LLM explanation (grounded on evidence)

The LLM is never allowed to invent arbitrary paths — targets are validated
against existing collections and indexed folders before they are suggested.
Accepting a *collection* suggestion adds the file to the target collection;
accepting a *folder* suggestion (B6-05) runs the approved move workflow;
accepting a *duplicate-removal* suggestion (B6-04) moves the redundant copy
into the reversible app trash after explicit user approval. Nothing moves or
deletes without approval.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

from engines.config import (
    DUPLICATE_REMOVAL_MIN_CONFIDENCE,
    FOLDER_ORGANIZATION_ENABLED,
    FOLDER_ORGANIZATION_MAX_TARGETS,
    SUGGESTION_MAX_TARGETS,
    SUGGESTION_MIN_CONFIDENCE,
)

from .batch5_models import DuplicateRemovalSuggestion, SuggestionInfo
from .batch5_store import Batch5Store

logger = logging.getLogger(__name__)


def _mtime_key(path: str) -> float:
    """Tie-break for equally-scored copies: prefer the newest file."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0

# Filename markers that indicate a copy / derivative (B6 §9.3).
_COPY_MARKERS = (
    "copy", "copie", "- copy", "_copy", "(copy)", "(1)", "(2)", "(3)",
    "-1", "_1", "-2", "_2", "-01", "_01", "-02", "_02", "~",
    ".bak", ".tmp", ".old", "-old", "_old", "duplicate", "(final)",
    "-final2", "_final2", " - copy", " (1)", " (2)", " (3)",
)
_TEMP_DIR_MARKERS = (os.sep + "tmp" + os.sep, "/var/tmp/", ".Trash", "trash", "cache" + os.sep)

# Taxonomy folder names considered for category-based organization (B6 §10.3).
_CATEGORY_FOLDER_NAMES = {
    "document": ["Documents", "Documentation", "Docs", "Notes"],
    "image": ["Images", "Pictures", "Photos", "Graphics"],
    "audio": ["Audio", "Music", "Podcasts", "Recordings"],
    "video": ["Video", "Videos", "Movies", "Footage"],
    "code": ["Code", "Source", "Projects", "Development"],
    "presentation": ["Presentations", "Slides", "Decks"],
    "spreadsheet": ["Spreadsheets", "Data", "Sheets"],
    "research": ["Research", "Papers", "Literature"],
    "education": ["Education", "Courses", "Learning", "Study"],
    "business": ["Business", "Work", "Office", "Reports"],
    "personal": ["Personal", "Private", "Family"],
    "archive": ["Archive", "Backups", "Old", "Legacy"],
    "project": ["Projects", "Roadmaps"],
    "data": ["Data", "Datasets"],
}


class SuggestionEngine:
    """Generates and manages organization suggestions."""

    def __init__(
        self,
        store: Batch5Store,
        related=None,
        classifier=None,
        tagger=None,
        collection_engine=None,
        rag=None,
        min_confidence: float = SUGGESTION_MIN_CONFIDENCE,
        max_targets: int = SUGGESTION_MAX_TARGETS,
        session_factory=None,
        retrieval=None,
        db_store=None,
        vector_engine=None,
        folder_org_enabled: bool = FOLDER_ORGANIZATION_ENABLED,
        removal_min_confidence: float = DUPLICATE_REMOVAL_MIN_CONFIDENCE,
        folder_org_max_targets: int = FOLDER_ORGANIZATION_MAX_TARGETS,
    ) -> None:
        """Args:
            store: Batch5Store.
            related: RelatedFileService (for related-file evidence).
            classifier: ClassificationEngine.
            tagger: TaggingEngine.
            collection_engine: CollectionEngine (target pool).
            rag: RAGEngine (optional LLM explanation).
            session_factory / retrieval / db_store / vector_engine: used by
                the approved duplicate-removal trash path (B6-04).
            folder_org_enabled: allow folder targets (B6-05).
            removal_min_confidence: floor for duplicate-removal suggestions.
        """
        self._store = store
        self._related = related
        self._classifier = classifier
        self._tagger = tagger
        self._collections = collection_engine
        self._rag = rag
        self._min_confidence = min_confidence
        self._max_targets = max_targets
        self._session_factory = session_factory
        self._retrieval = retrieval
        self._db_store = db_store
        self._vector_engine = vector_engine
        self._folder_org_enabled = folder_org_enabled
        self._removal_min_confidence = removal_min_confidence
        self._folder_org_max_targets = folder_org_max_targets

    # ------------------------------------------------------------------ #
    def suggest_for_file(self, file_path: str, reason_depth: str = "short") -> List[SuggestionInfo]:
        """Generate (and persist) suggestions for one file.

        Returns the persisted suggestion list (may be empty).
        """
        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            return []

        # 1. Candidate targets — existing collections (no invention).
        #    Folder targets (B6-05) are appended below, so an empty collection
        #    pool must not short-circuit the whole suggestion set.
        targets = self._candidate_collections()
        if not targets and not self._folder_org_enabled:
            return []

        # 2. Evidence: related files + category + tags.
        related_paths: List[str] = []
        if self._related is not None:
            try:
                related_paths = [
                    os.path.abspath(r.file_path)
                    for r in self._related.related_files(file_path)
                ][:20]
            except Exception as exc:
                logger.debug("Related evidence failed: %s", exc)
        category = self._category_of(file_path)
        tags = self._tags_of(file_path)

        # 3. Score each target from the evidence.
        scored = []
        for target in targets:
            score = self._score_target(target, related_paths, category, tags)
            if score >= self._min_confidence:
                scored.append((score, target))

        scored.sort(key=lambda st: st[0], reverse=True)
        scored = scored[: self._max_targets]

        # 4. Optional LLM explanation, grounded on evidence (best target only).
        if scored and self._rag is not None and reason_depth == "full":
            self._explain_with_llm(file_path, scored[0], related_paths, category, tags)

        # 4b. B6-05 — deterministic folder targets (existing folders only).
        if self._folder_org_enabled:
            for folder in self.folder_targets_for_file(file_path):
                scored.append((folder["confidence"], folder))
                if len(scored) >= self._max_targets + self._folder_org_max_targets:
                    break

        # 5. Persist + return.
        suggestions = []
        for score, target in scored:
            try:
                sid = self._store.create_suggestion(
                    file_path=file_path,
                    suggested_target=target["name"],
                    target_type=target.get("type", "collection"),
                    reason=self._reason_text(target, related_paths, category, tags),
                    confidence=round(score, 4),
                )
                suggestions.append(self._store_suggestion(sid))
            except Exception as exc:
                logger.debug("Suggestion persistence failed: %s", exc)
        return suggestions

    def _store_suggestion(self, sid: int) -> SuggestionInfo:
        for s in self._store.list_suggestions():
            if s.id == sid:
                return s
        return SuggestionInfo(id=sid, file_path="", suggested_target="", confidence=0.0)

    # ------------------------------------------------------------------ #
    def accept(self, suggestion_id: int) -> bool:
        """Accept a suggestion → add the file to the target collection.

        Never moves physical files. If the target is a collection it must
        still exist; otherwise the suggestion is marked expired.
        """
        suggestion = self._suggestion(suggestion_id)
        if suggestion is None:
            return False
        if suggestion.status != "pending":
            return False
        if suggestion.target_type == "collection":
            # Collection targets must always resolve to a real collection;
            # without a collection engine we cannot verify the target.
            if self._collections is None:
                self._store.set_suggestion_status(suggestion_id, "expired")
                return False
            collection = self._collection_by_name(suggestion.suggested_target)
            if collection is None:
                self._store.set_suggestion_status(suggestion_id, "expired")
                return False
            self._collections.add_member(collection.id, suggestion.file_path)
        self._store.set_suggestion_status(suggestion_id, "accepted")
        return True

    def dismiss(self, suggestion_id: int) -> bool:
        return self._store.set_suggestion_status(suggestion_id, "dismissed")

    # ------------------------------------------------------------------ #
    # B6-05 — folder organization targets
    # ------------------------------------------------------------------ #
    def folder_targets_for_file(self, file_path: str) -> List[dict]:
        """Deterministic folder targets for a file (existing folders only).

        Candidate pool: sibling directories of the file whose name matches the
        file's category (or the taxonomy folder-name list). Never invents
        directories. Returns [{name, path, type: 'folder', confidence}].
        """
        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            return []
        parent = os.path.dirname(file_path)
        try:
            siblings = [
                os.path.join(parent, d)
                for d in os.listdir(parent)
                if os.path.isdir(os.path.join(parent, d))
            ]
        except OSError:
            return []
        if not siblings:
            return []

        category = self._category_of(file_path)
        targets = []
        for folder in siblings:
            base = os.path.basename(folder).lower()
            if base in (os.path.basename(parent).lower(),):
                continue
            matched = (
                category and base in (name.lower() for name in _CATEGORY_FOLDER_NAMES.get(category, []))
            ) or (category and category in base)
            if not matched:
                continue
            targets.append({
                "name": os.path.basename(folder),
                "path": folder,
                "type": "folder",
                "confidence": 0.72 if category and category in base else 0.66,
            })
            if len(targets) >= self._folder_org_max_targets:
                break
        return targets

    # ------------------------------------------------------------------ #
    # B6-04 — duplicate-removal suggestions
    # ------------------------------------------------------------------ #
    def suggest_duplicate_removals(
        self,
        groups,
        duplicate_type: str = "exact",
    ) -> List[DuplicateRemovalSuggestion]:
        """Recommend which copy of each duplicate group to remove (persisted).

        ``groups``: iterable of objects with ``checksum`` and ``files``
        (DuplicateGroup for exact; ad-hoc groups for near duplicates).
        Advisory only — nothing is deleted here.
        """
        suggestions: List[DuplicateRemovalSuggestion] = []
        for group in groups:
            files = [os.path.abspath(p) for p in getattr(group, "files", []) if p and os.path.isfile(p)]
            if len(files) < 2:
                continue
            keep = self._best_copy(files)
            for remove in files:
                if remove == keep:
                    continue
                confidence = self._removal_confidence(keep, remove, duplicate_type)
                if confidence < self._removal_min_confidence:
                    continue
                try:
                    sid = self._store.create_duplicate_suggestion(
                        group_checksum=getattr(group, "checksum", "") or "",
                        keep_path=keep,
                        remove_path=remove,
                        duplicate_type=duplicate_type,
                        confidence=round(confidence, 4),
                        reason=self._removal_reason(keep, remove, duplicate_type, group),
                        evidence=self._removal_evidence(keep, remove, duplicate_type, group),
                    )
                    item = self._store.get_duplicate_suggestion(sid)
                    if item is not None:
                        suggestions.append(item)
                except Exception as exc:
                    logger.debug("Duplicate suggestion persistence failed: %s", exc)
        return suggestions

    def suggest_near_duplicate_removals(
        self,
        pairs: List[Tuple[str, str, float]],
        min_similarity: float = 0.90,
    ) -> List[DuplicateRemovalSuggestion]:
        """Recommend removals for near-duplicate (path, path, score) pairs.

        Each pair is scored independently; only scores above the floor yield
        a persisted suggestion.
        """
        suggestions: List[DuplicateRemovalSuggestion] = []
        for a, b, score in pairs:
            a, b = os.path.abspath(a), os.path.abspath(b)
            if a == b or score < min_similarity:
                continue
            keep = self._best_copy([a, b])
            remove = b if keep == a else a
            confidence = 0.5 + 0.4 * score
            if confidence < self._removal_min_confidence:
                continue
            try:
                sid = self._store.create_duplicate_suggestion(
                    group_checksum="",
                    keep_path=keep,
                    remove_path=remove,
                    duplicate_type="near",
                    confidence=round(confidence, 4),
                    reason=(
                        f"Very similar content ({score:.0%} similarity). "
                        + self._filename_reason(keep, remove)
                    ),
                    evidence={"similarity": round(score, 4), "checksum": None},
                )
                item = self._store.get_duplicate_suggestion(sid)
                if item is not None:
                    suggestions.append(item)
            except Exception as exc:
                logger.debug("Near-duplicate suggestion persistence failed: %s", exc)
        return suggestions

    def accept_duplicate_removal(self, suggestion_id: int) -> dict:
        """Execute an approved removal: move the file to the reversible trash.

        Returns {"ok": bool, "trash_path": str, "error": str}. Nothing is
        permanently deleted; the index is synchronized through the existing
        cleanup path. The suggestion is marked ``executed`` only on success.
        """
        suggestion = self._store.get_duplicate_suggestion(suggestion_id)
        if suggestion is None:
            return {"ok": False, "error": "The suggestion no longer exists."}
        if suggestion.status != "pending":
            return {"ok": False, "error": f"Suggestion already {suggestion.status}."}
        if not os.path.isfile(suggestion.remove_path):
            self._store.set_duplicate_suggestion_status(suggestion_id, "expired")
            return {"ok": False, "error": "The file to remove no longer exists."}
        if os.path.abspath(suggestion.remove_path) == os.path.abspath(suggestion.keep_path):
            return {"ok": False, "error": "Keep and remove paths are identical."}

        from .safe_file_ops import move_to_trash

        try:
            result = move_to_trash(
                path=suggestion.remove_path,
                session_factory=self._session_factory,
                retrieval=self._retrieval,
                db_store=self._db_store,
                vector_engine=self._vector_engine,
            )
        except Exception as exc:
            logger.error("Trash move failed for %s: %s", suggestion.remove_path, exc)
            return {"ok": False, "error": str(exc)}

        if not result.ok:
            return {"ok": False, "error": result.error or "Removal failed."}
        self._store.set_duplicate_suggestion_status(suggestion_id, "executed")
        return {"ok": True, "trash_path": result.target}

    def dismiss_duplicate_removal(self, suggestion_id: int) -> bool:
        return self._store.set_duplicate_suggestion_status(suggestion_id, "dismissed")

    # ------------------------------------------------------------------ #
    # Duplicate-removal heuristics (B6 §9.3)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _best_copy(paths: List[str]) -> str:
        """Pick the copy most likely to be the 'original' to keep."""
        best = max(paths, key=lambda p: (SuggestionEngine._keep_score(p), _mtime_key(p)))
        return best

    @staticmethod
    def _keep_score(path: str) -> float:
        """Higher = more canonical / safer to keep."""
        name = os.path.basename(path).lower()
        score = 0.0
        if not any(marker in name for marker in _COPY_MARKERS):
            score += 0.4
        if not name.startswith("."):
            score += 0.3
        lowered_path = path.lower()
        if not any(marker in lowered_path for marker in _TEMP_DIR_MARKERS):
            score += 0.3
        return score

    def _removal_confidence(self, keep: str, remove: str, duplicate_type: str) -> float:
        if duplicate_type == "exact":
            return 1.0  # 100% confidence for exact SHA-256 byte-for-byte duplicate match
        diff = self._keep_score(keep) - self._keep_score(remove)
        confidence = 0.78 + 0.10 * diff
        return max(0.55, min(0.98, confidence))

    def _removal_reason(self, keep: str, remove: str, duplicate_type: str, group) -> str:
        parts = []
        if duplicate_type == "exact":
            parts.append("100% Identical Content Match (same SHA-256 checksum)")
        else:
            parts.append("High Content Similarity (Near Duplicate)")
        if os.path.isfile(keep) and os.path.isfile(remove) and os.path.getsize(keep) == os.path.getsize(remove):
            parts.append("Same file size")
        parts.append(self._filename_reason(keep, remove))
        return "; ".join(parts)

    @staticmethod
    def _filename_reason(keep: str, remove: str) -> str:
        keep_name = os.path.basename(keep).lower()
        remove_name = os.path.basename(remove).lower()
        if any(m in remove_name for m in _COPY_MARKERS):
            return f"'{os.path.basename(remove)}' looks like a copy ('{os.path.basename(keep)}' kept)"
        if remove_name.startswith("."):
            return "The removed copy is a hidden file"
        return f"Keeping '{os.path.basename(keep)}' as the canonical copy"

    @staticmethod
    def _removal_evidence(keep: str, remove: str, duplicate_type: str, group) -> dict:
        evidence = {
            "checksum": getattr(group, "checksum", "") or "",
            "duplicate_type": duplicate_type,
            "keep_size": os.path.getsize(keep) if os.path.isfile(keep) else 0,
            "remove_size": os.path.getsize(remove) if os.path.isfile(remove) else 0,
        }
        return evidence

    # ------------------------------------------------------------------ #
    # Evidence helpers
    # ------------------------------------------------------------------ #
    def _candidate_collections(self) -> List[dict]:
        if self._collections is None:
            return []
        try:
            return [
                {"name": c.name, "type": "collection", "id": c.id, "is_smart": c.is_smart}
                for c in self._collections.list()
            ]
        except Exception:
            return []

    def _category_of(self, path: str) -> str:
        if self._classifier is not None:
            cat = self._classifier.category_for_path(path)
            if cat:
                return cat
        from services.classification_engine import category_from_extension
        return category_from_extension(path)

    def _tags_of(self, path: str) -> List[str]:
        if self._tagger is not None:
            return self._tagger.tags_for_path(path)
        return []

    def _score_target(
        self,
        target: dict,
        related_paths: List[str],
        category: str,
        tags: List[str],
    ) -> float:
        """Deterministic evidence-based confidence in [0, 1].

        Components:
          - overlap: related files already members of the target collection
          - category: target is the natural category collection for this file
          - tags:    target's member files share the file's canonical tags
        """
        score = 0.0
        members = self._member_paths(target)
        if not members:
            return 0.0

        if related_paths:
            overlap = len(set(related_paths) & set(members))
            score += min(1.0, overlap / max(1, min(len(related_paths), 5))) * 0.6

        if category:
            cat_members = sum(
                1 for m in members
                if self._category_of(m) == category
            )
            if cat_members and cat_members / len(members) >= 0.5:
                score += 0.25

        if tags:
            tag_hits = 0
            for m in members:
                if set(self._tags_of(m)) & set(tags):
                    tag_hits += 1
            if tag_hits and tag_hits / len(members) >= 0.5:
                score += 0.15

        return min(1.0, score)

    def _member_paths(self, target: dict) -> List[str]:
        try:
            return self._collections.member_paths(target.get("id", 0))
        except Exception:
            return []

    def _reason_text(
        self,
        target: dict,
        related_paths: List[str],
        category: str,
        tags: List[str],
    ) -> str:
        parts = []
        members = self._member_paths(target)
        overlap = len(set(related_paths) & set(members))
        if overlap:
            parts.append(f"{overlap} related files belong to this collection")
        if category:
            parts.append(f"file category: {category}")
        if tags:
            parts.append("shared tags: " + ", ".join(tags[:3]))
        return "; ".join(parts) if parts else "Candidate collection based on indexed organization"

    def _explain_with_llm(
        self,
        file_path: str,
        target,
        related_paths: List[str],
        category: str,
        tags: List[str],
    ) -> None:
        """Optional LLM explanation — grounded, never path-inventing.

        The prompt lists ONLY existing targets and evidence; the model is
        explicitly told not to propose other locations.
        """
        try:
            prompt = (
                "You are organizing a local file archive. Suggest ONE short reason why the "
                "following file could belong to the suggested collection.\n\n"
                f"File: {os.path.basename(file_path)}\n"
                f"Category: {category or 'unknown'}\n"
                f"Tags: {', '.join(tags) or 'none'}\n"
                f"Related files ({len(related_paths)}): "
                f"{', '.join(os.path.basename(p) for p in related_paths[:6])}\n"
                f"Suggested collection: {target['name']}\n\n"
                "Reply with only 1-2 sentences. Do NOT propose any other folder or path."
            )
            explanation = self._rag._generate(prompt)[:240]
            if explanation:
                self._store.update_suggestion_reason(self._find_pending_id(file_path), explanation)
        except Exception as exc:
            logger.debug("LLM explanation skipped: %s", exc)

    def _find_pending_id(self, file_path: str) -> int:
        for s in self._store.suggestions_for_path(file_path):
            if s.status == "pending":
                return s.id
        return 0

    # ------------------------------------------------------------------ #
    def _suggestion(self, suggestion_id: int) -> Optional[SuggestionInfo]:
        for s in self._store.list_suggestions():
            if s.id == suggestion_id:
                return s
        return None

    def _collection_by_name(self, name: str):
        if self._collections is None:
            return None
        for c in self._collections.list():
            if c.name == name:
                return c
        return None
