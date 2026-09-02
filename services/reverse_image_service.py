"""Reverse image search service — B7-1 (#6).

Finds visually similar indexed images from a query image:

    Query Image
        ↓ CLIP embed_image()
        ↓ FAISS search (padded to the shared embedding dimension)
        ↓ filter to image evidence (source_type clip_visual / image modality)
        ↓ rank + threshold
        ↓ results

Reuses the existing CLIPEngine and the single FAISS index — no second
vector database. CLIP vectors were already stored (padded to the text
embedding dimension) during AI indexing, so no re-embedding of indexed
images is needed.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ReverseImageResult:
    """One visually-similar indexed image."""

    file_path: str
    score: float
    chunk_id: str = ""
    source_label: str = "Visual Content"

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "score": round(self.score, 4),
            "chunk_id": self.chunk_id,
            "source_label": self.source_label,
        }


class ReverseImageService:
    """Query-by-image similarity search over the existing FAISS index."""

    def __init__(
        self,
        retrieval=None,
        clip_engine=None,
        min_similarity: float = 0.55,
        max_results: int = 12,
    ) -> None:
        self._retrieval = retrieval
        self._clip = clip_engine
        self._min_similarity = min_similarity
        self._max_results = max_results

    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        if self._retrieval is None:
            return False
        if self._clip is None:
            return False
        try:
            return self._clip.is_available()
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    def search_by_image(
        self,
        image_path: str,
        top_k: Optional[int] = None,
        threshold: Optional[float] = None,
    ) -> List[ReverseImageResult]:
        """Search for visually similar indexed images.

        Returns [] when CLIP is unavailable, the query image is unreadable,
        or the index is empty.
        """
        if not self.is_available():
            return []
        if not os.path.isfile(image_path):
            return []
        top_k = top_k or self._max_results
        threshold = threshold if threshold is not None else self._min_similarity

        try:
            vector = self._clip.embed_image(image_path)
            if vector is None:
                return []
            vector = self._pad(vector)
            # Query the entire index size to ensure we get all candidate visual chunks
            # for filtering, since text/OCR chunks can dominate the raw results.
            total_size = 1000
            if hasattr(self._retrieval._vector, "size"):
                total_size = self._retrieval._vector.size
            elif hasattr(self._retrieval._vector, "ntotal"):
                total_size = self._retrieval._vector.ntotal
            elif hasattr(self._retrieval, "indexed_count"):
                total_size = self._retrieval.indexed_count

            search_k = max(top_k * 10, total_size)
            raw = self._retrieval._vector.search(
                vector, top_k=search_k, threshold=0.1
            )
        except Exception as exc:
            logger.debug("Reverse image search failed: %s", exc)
            return []

        results: List[ReverseImageResult] = []
        seen_files = set()
        for sr in raw:
            if sr.score < threshold:
                continue
            chunk = self._retrieval._evidence.get(sr.chunk_id)
            if chunk is None:
                continue
            # Compare CLIP query vector ONLY against CLIP visual vectors (source_type == "clip_visual")
            # to exclude text-embedded OCR, caption, and document vectors.
            if chunk.source_type != "clip_visual":
                continue
            # Exclude the query image itself from results
            if os.path.abspath(chunk.file_path) == os.path.abspath(image_path):
                continue
            if chunk.file_path in seen_files:
                continue
            seen_files.add(chunk.file_path)
            results.append(ReverseImageResult(
                file_path=chunk.file_path,
                score=sr.score,
                chunk_id=sr.chunk_id,
                source_label=chunk.source_label or "Visual Content",
            ))
            if len(results) >= top_k:
                break

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    # ------------------------------------------------------------------ #
    def _pad(self, vector: np.ndarray) -> np.ndarray:
        """Pad a CLIP vector to the shared FAISS embedding dimension."""
        dim = self._retrieval._vector.dimension
        if vector.shape[0] == dim:
            return vector.astype(np.float32)
        padded = np.zeros(dim, dtype=np.float32)
        n = min(vector.shape[0], dim)
        padded[:n] = vector[:n]
        norm = np.linalg.norm(padded)
        if norm > 1e-8:
            padded = padded / norm
        return padded
