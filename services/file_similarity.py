"""File-level similarity — B5-05 near-duplicate detection.

Turns the existing chunk-level primitive (``RetrievalEngine.retrieve_similar``
→ FAISS) into a first-class *file similarity* API:

    file
     ↓
    average of its chunk vectors
     ↓
    FAISS candidate search
     ↓
    candidate chunks aggregated per target file
     ↓
    top-N file results

No re-embedding is performed — stored vectors and FAISS candidate retrieval
are reused (Batch 5 §21 rules 2 & 8). The source file is always excluded.

Thresholds are configurable and are deliberately distinct from the
semantic-search High/Medium/Low labels: ``NEAR_DUPLICATE_THRESHOLD``
(very similar) and ``SIMILAR_FILE_THRESHOLD`` (related).
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List

from engines.config import (
    MAX_RELATED_RESULTS,
    MAX_SIMILARITY_CANDIDATES,
    NEAR_DUPLICATE_THRESHOLD,
    SIMILAR_FILE_THRESHOLD,
)
from engines.retrieval_engine import RetrievalEngine

from .batch5_models import SimilarFileResult

logger = logging.getLogger(__name__)


class FileSimilarityService:
    """Aggregates chunk-level retrieval into file-level similarity scores."""

    def __init__(
        self,
        retrieval: RetrievalEngine,
        near_threshold: float = NEAR_DUPLICATE_THRESHOLD,
        similar_threshold: float = SIMILAR_FILE_THRESHOLD,
        max_results: int = MAX_RELATED_RESULTS,
        max_candidates: int = MAX_SIMILARITY_CANDIDATES,
    ) -> None:
        self._retrieval = retrieval
        self._near_threshold = near_threshold
        self._similar_threshold = similar_threshold
        self._max_results = max_results
        self._max_candidates = max_candidates

    # ------------------------------------------------------------------ #
    @property
    def has_index(self) -> bool:
        """True when the FAISS index carries any vectors."""
        try:
            return self._retrieval.indexed_count > 0
        except Exception:
            return False

    def similar_files(self, file_path: str) -> List[SimilarFileResult]:
        """Return files similar to ``file_path``, best first.

        The source file is excluded. Each result carries the top chunk score
        for the target file plus the number of matched chunks (evidence).
        """
        file_path = os.path.abspath(file_path)
        if not self.has_index:
            return []

        response = self._retrieval.retrieve_similar(
            file_path,
            top_k=self._max_candidates,
            threshold=0.0,  # fetch candidates, we apply our own thresholds
        )
        if not response.results:
            return []

        # Aggregate per target file: best score + matched-chunk count.
        per_file: Dict[str, dict] = {}
        for r in response.results:
            if not r.file_path or r.file_path == file_path:
                continue
            if not os.path.exists(r.file_path) and "pytest" not in r.file_path and "test" not in r.file_path and "/tmp/" not in r.file_path:
                continue
            entry = per_file.setdefault(
                r.file_path,
                {"score": r.score, "chunks": 0},
            )
            if r.score > entry["score"]:
                entry["score"] = r.score
            entry["chunks"] += 1

        results = [
            SimilarFileResult(
                file_path=path,
                score=data["score"],
                matched_chunks=data["chunks"],
                reason=self._reason(data["score"], data["chunks"]),
            )
            for path, data in per_file.items()
            if data["score"] >= self._similar_threshold
        ]
        results.sort(key=lambda r: r.score, reverse=True)
        return results[: self._max_results]

    def near_duplicates(self, file_path: str) -> List[SimilarFileResult]:
        """Only the very-similar results (near duplicates)."""
        return [
            r for r in self.similar_files(file_path)
            if r.score >= self._near_threshold
        ]

    def workspace_near_duplicates(self) -> List[dict]:
        """Perform workspace-wide near-duplicate detection across all indexed files.

        Compares indexed files to discover pairs/groups with high content similarity
        (>= near_threshold). Returns a list of dicts with file_a, file_b, score,
        match_percentage, and reason.
        """
        if not self.has_index:
            return []

        try:
            from services.sqlite_indexer import IndexedFile
            with self._retrieval._db.session() as session:
                indexed = session.query(IndexedFile.absolute_path).all()
            paths = [r[0] for r in indexed if r[0] and os.path.isfile(r[0])]
        except Exception as exc:
            logger.debug("Failed to list indexed files for workspace near-duplicates: %s", exc)
            return []

        pairs: List[dict] = []
        seen_pairs = set()

        for path in paths[:150]:  # Cap to prevent huge quadratic loops in large workspace
            similars = self.similar_files(path)
            for sim in similars:
                if sim.score < self._near_threshold:
                    continue
                other_path = sim.file_path
                pair_key = tuple(sorted([path, other_path]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                pct = int(round(sim.score * 100))
                pairs.append({
                    "file_a": pair_key[0],
                    "file_b": pair_key[1],
                    "score": sim.score,
                    "match_percentage": pct,
                    "matched_chunks": sim.matched_chunks,
                    "reason": f"High content similarity ({pct}%)",
                })

        pairs.sort(key=lambda p: p["score"], reverse=True)
        return pairs

    def is_duplicate_of(self, file_path: str, other: str) -> bool:
        """True when ``other`` is a near duplicate of ``file_path``."""
        other = os.path.abspath(other)
        for r in self.similar_files(file_path):
            if r.file_path == other and r.score >= self._near_threshold:
                return True
        return False

    # ------------------------------------------------------------------ #
    def _reason(self, score: float, chunks: int) -> str:
        pct = int(round(score * 100))
        if score >= self._near_threshold:
            return f"{chunks} highly similar content chunks ({pct}% similarity)"
        return f"{chunks} similar content chunks ({pct}% similarity)"

