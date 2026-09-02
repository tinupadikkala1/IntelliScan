"""AI image filtering service — B7-10 (#30).

Filters indexed images using AI-derived visual attributes:

    User query (e.g. "images with dogs", "screenshots", "blurry images")
        ↓ filter parsing (objects / captions / quality / text presence)
        ↓ existing indexed AI metadata (objects_json, captions, quality)
        ↓ cheap candidate filtering (no inference during search)
        ↓ optional semantic re-ranking via CLIP text embedding
        ↓ results

Prefers existing indexed metadata over running expensive inference on every
search. When a semantic concept is requested and CLIP is available, a text
embedding re-rank is applied on the surviving candidates only.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Object labels commonly requested in natural language filters.
_OBJECT_SYNONYMS = {
    "dog": ["dog", "dogs", "puppy", "puppies", "canine"],
    "cat": ["cat", "cats", "kitten", "kittens", "feline"],
    "person": ["person", "people", "human", "man", "woman", "child", "children"],
    "car": ["car", "cars", "vehicle", "automobile", "truck", "bus"],
    "screenshot": ["screenshot", "screenshots", "screen capture", "ui", "interface"],
    "text": ["text", "caption", "screenshot"],
    "landscape": ["landscape", "outdoor", "nature", "scenery", "mountain"],
    "animal": ["animal", "animals", "bird", "horse", "cow", "sheep"],
    "building": ["building", "house", "city", "architecture"],
    "food": ["food", "meal", "dish", "pizza", "coffee"],
}

_QUALITY_WORDS = {
    "blurry": "Blurry",
    "blurred": "Blurry",
    "sharp": "Sharp",
    "clear": "Sharp",
    "dark": "Dark",
    "underexposed": "Dark",
    "bright": "Bright",
    "overexposed": "Bright",
    "low quality": "Poor",
    "poor quality": "Poor",
    "high quality": "Good",
    "good quality": "Good",
}


@dataclass
class ImageFilterCriteria:
    """Parsed filter criteria from a natural-language query."""

    objects: List[str] = field(default_factory=list)      # labels to require
    quality: Optional[str] = None                          # Blurry/Sharp/Dark/Bright/Good/Poor
    caption_keywords: List[str] = field(default_factory=list)
    require_text: bool = False
    semantic: Optional[str] = None                         # free-form concept

    def is_empty(self) -> bool:
        return not (self.objects or self.quality or self.caption_keywords
                    or self.require_text or self.semantic)


@dataclass
class ImageFilterHit:
    """One image surviving the filter."""

    file_path: str
    reason: str = ""
    score: float = 1.0
    quality_label: str = ""

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "reason": self.reason,
            "score": round(self.score, 4),
            "quality_label": self.quality_label,
        }


class ImageFilterService:
    """Filters indexed images by AI-derived attributes."""

    def __init__(self, session_factory, reverse_image_service=None) -> None:
        self._session_factory = session_factory
        self._reverse = reverse_image_service

    # ------------------------------------------------------------------ #
    def parse_query(self, query: str) -> ImageFilterCriteria:
        """Parse a natural-language image filter query (deterministic)."""
        q = (query or "").lower()
        crit = ImageFilterCriteria()

        for label, synonyms in _OBJECT_SYNONYMS.items():
            for word in synonyms:
                if f" {word} " in f" {q} " or q.startswith(word + " ") or q.endswith(" " + word):
                    if label not in crit.objects:
                        crit.objects.append(label)
                    break

        for keyword, quality in _QUALITY_WORDS.items():
            if keyword in q:
                crit.quality = quality
                break

        if "with text" in q or "containing text" in q or "has text" in q:
            crit.require_text = True

        # Strip the handled phrases; whatever remains is a semantic concept.
        remainder = q
        for word in sum(list(_OBJECT_SYNONYMS.values()), []):
            remainder = remainder.replace(f" {word} ", " ").strip()
        for keyword in _QUALITY_WORDS:
            remainder = remainder.replace(keyword, " ").strip()
        for phrase in ("images", "image", "photos", "photo", "pictures", "picture",
                       "that", "with", "of", "containing", "showing", "has", "have",
                       "the", "a", "an", "and", "or"):
            remainder = remainder.replace(f" {phrase} ", " ").strip()
        remainder = remainder.strip(" ,;:-")
        if remainder and len(remainder) >= 3:
            crit.semantic = remainder

        return crit

    # ------------------------------------------------------------------ #
    def filter_images(
        self,
        query: str,
        folder: Optional[str] = None,
        threshold: float = 0.45,
        limit: int = 50,
    ) -> List[ImageFilterHit]:
        """Filter indexed images against a natural-language query."""
        crit = self.parse_query(query)
        if crit.is_empty():
            return []

        images = self._collect_images(folder=folder)
        hits: List[ImageFilterHit] = []

        for path, meta in images.items():
            reason = self._matches(path, meta, crit)
            if reason is None:
                continue
            quality_label = ""
            if meta.get("quality"):
                quality_label = meta["quality"].get("label", "")
            hits.append(ImageFilterHit(
                file_path=path,
                reason=reason,
                quality_label=quality_label,
            ))

        # Optional semantic re-rank when a concept remains and CLIP is up.
        if crit.semantic and self._reverse is not None and hits:
            try:
                ranked = self._semantic_rank(crit.semantic, hits, threshold)
                if ranked:
                    hits = ranked
            except Exception as exc:
                logger.debug("semantic re-rank failed: %s", exc)

        return hits[:limit]

    # ------------------------------------------------------------------ #
    def _collect_images(self, folder: Optional[str] = None) -> Dict[str, dict]:
        """Map absolute image path → {objects, caption, quality} from index."""
        out: Dict[str, dict] = {}
        try:
            from services.sqlite_indexer import IndexedFile
            from database.models import AIAnalysis

            with self._session_factory() as session:
                rows = session.query(IndexedFile).all()
                prefix = folder.rstrip(os.sep) + os.sep if folder else None
                for r in rows:
                    p = r.absolute_path or ""
                    if prefix and not p.startswith(prefix):
                        continue
                    ext = os.path.splitext(p)[1].lower()
                    if ext not in {
                        ".png", ".jpg", ".jpeg", ".webp", ".bmp",
                        ".tiff", ".tif", ".gif",
                    }:
                        continue
                    out[p] = {"objects": [], "caption": "", "quality": None}
                checksums = {
                    r.checksum for r in rows
                    if r.absolute_path in out and r.checksum and len(r.checksum) == 64
                }
                if checksums:
                    ai_rows = (
                        session.query(AIAnalysis)
                        .filter(AIAnalysis.file_hash.in_(checksums))
                        .all()
                    )
                    hash_to_path = {
                        r.checksum: r.absolute_path for r in rows
                        if r.absolute_path in out and r.checksum
                    }
                    for row in ai_rows:
                        path = hash_to_path.get(row.file_hash)
                        if path is None:
                            continue
                        meta = out[path]
                        if row.objects_json:
                            try:
                                objs = json.loads(row.objects_json)
                                meta["objects"] = [
                                    str(o.get("label", "")) for o in objs
                                    if isinstance(o, dict) and o.get("label")
                                ]
                            except (json.JSONDecodeError, TypeError):
                                pass
                        meta["caption"] = row.caption or ""
                        if row.quality_json:
                            try:
                                meta["quality"] = json.loads(row.quality_json)
                            except (json.JSONDecodeError, TypeError):
                                meta["quality"] = None
        except Exception as exc:
            logger.debug("image collection failed: %s", exc)
        return out

    # ------------------------------------------------------------------ #
    def _matches(self, path: str, meta: dict, crit: ImageFilterCriteria) -> Optional[str]:
        reasons = []

        objects = meta.get("objects") or []
        caption = (meta.get("caption") or "").lower()
        for label in crit.objects:
            synonyms = _OBJECT_SYNONYMS.get(label, [label])
            matched_obj = any(
                any(s in o.lower() for s in synonyms) for o in objects
            )
            # Some concepts are discoverable from the caption alone.
            matched_cap = False
            if label == "text":
                matched_cap = any(w in caption for w in ("text", "screen", "ui"))
            elif label == "screenshot":
                matched_cap = any(
                    w in caption for w in ("screenshot", "screen", "ui", "interface")
                )
            if not matched_obj and not matched_cap:
                return None  # required concept absent
            reasons.append(f"contains {label}")

        if crit.require_text:
            caption = (meta.get("caption") or "").lower()
            if not (caption and any(w in caption for w in ("text", "screen", "ui"))):
                return None
            reasons.append("contains text")

        if crit.quality:
            qlabel = (meta.get("quality") or {}).get("label", "") or ""
            score = (meta.get("quality") or {}).get("score", 0.0) or 0.0
            if crit.quality in ("Blurry", "Dark", "Bright") and qlabel != crit.quality:
                return None
            if crit.quality == "Sharp" and qlabel not in ("Good", "Sharp"):
                return None
            if crit.quality == "Good" and score < 0.6:
                return None
            if crit.quality == "Poor" and score >= 0.6:
                return None
            reasons.append(crit.quality.lower())

        for kw in crit.caption_keywords:
            if kw.lower() not in (meta.get("caption") or "").lower():
                return None
            reasons.append(f"caption '{kw}'")

        if not reasons and not crit.semantic:
            return None
        return "; ".join(reasons) if reasons else "semantic match"

    # ------------------------------------------------------------------ #
    def _semantic_rank(
        self, concept: str, hits: List[ImageFilterHit], threshold: float
    ) -> List[ImageFilterHit]:
        """Re-rank candidates by CLIP text-embedding similarity."""
        if self._reverse is None or self._reverse._clip is None:
            return hits
        clip = self._reverse._clip
        text_vec = clip.embed_text(concept)
        if text_vec is None:
            return hits
        scored = []
        for hit in hits:
            vec = clip.embed_image(hit.file_path)
            if vec is None:
                continue
            s = float(np.dot(text_vec, vec) / (
                (np.linalg.norm(text_vec) * np.linalg.norm(vec)) + 1e-8
            ))
            if s >= threshold:
                hit.score = s
                scored.append(hit)
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored
