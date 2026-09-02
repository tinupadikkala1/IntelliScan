"""Related-file discovery — B5-06.

Combines three independent scoring signals into one result list:

1. **similarity** — FileSimilarityService (chunk-vector aggregation over FAISS)
2. **graph**     — knowledge-graph shared-entity evidence (GraphStore)
3. **semantic**  — a natural-language query embedding against the workspace

Scores are kept separate and merged without pretending the signals share a
calibrated scale: each result carries its ``source`` and a human ``reason``.
The source file is always excluded and entries are deduplicated by path.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List

from engines.config import MAX_RELATED_RESULTS
from engines.retrieval_engine import RetrievalEngine, RetrievalScope

from .batch5_models import RelatedFileResult
from .file_similarity import FileSimilarityService

logger = logging.getLogger(__name__)


class RelatedFileService:
    """Combines similarity + graph + semantic signals into related files."""

    def __init__(
        self,
        retrieval: RetrievalEngine,
        similarity: FileSimilarityService,
        graph_store=None,
        max_results: int = MAX_RELATED_RESULTS,
    ) -> None:
        self._retrieval = retrieval
        self._similarity = similarity
        self._graph = graph_store
        self._max_results = max_results

    # ------------------------------------------------------------------ #
    def related_files(self, file_path: str) -> List[RelatedFileResult]:
        """Return related files for a path, best first, deduplicated."""
        file_path = os.path.abspath(file_path)
        merged: Dict[str, RelatedFileResult] = {}

        # 1. Vector similarity (chunk aggregation).
        for r in self._similarity.similar_files(file_path):
            merged[r.file_path] = RelatedFileResult(
                file_path=r.file_path,
                score=r.score,
                reason=r.reason,
                source="similarity",
            )

        # 2. Knowledge-graph shared entities.
        if self._graph is not None:
            try:
                for path in self._graph.files_sharing_entities(file_path):
                    path = os.path.abspath(path)
                    if path == file_path:
                        continue
                    existing = merged.get(path)
                    if existing is None:
                        merged[path] = RelatedFileResult(
                            file_path=path,
                            score=0.6,  # graph evidence, not a cosine score
                            reason="Shared topics/entities in the knowledge graph",
                            source="graph",
                        )
                    else:
                        existing.reason = (
                            f"{existing.reason}; shared topics/entities in the knowledge graph"
                        )
            except Exception as exc:
                logger.debug("Graph related-files failed: %s", exc)

        # 3. Semantic workspace search — topic-based query of the file.
        try:
            topic = self._topic_query(file_path)
            if topic:
                response = self._retrieval.smart_retrieve(
                    topic,
                    top_k=self._max_results,
                    threshold=0.0,
                )
                for r in response.results:
                    path = os.path.abspath(r.file_path)
                    if path == file_path:
                        continue
                    existing = merged.get(path)
                    if existing is None:
                        merged[path] = RelatedFileResult(
                            file_path=path,
                            score=r.score,
                            reason="Semantically related content",
                            source="semantic",
                        )
                    elif r.score > existing.score:
                        existing.score = r.score
        except Exception as exc:
            logger.debug("Semantic related-files failed: %s", exc)

        results = sorted(merged.values(), key=lambda r: r.score, reverse=True)
        return results[: self._max_results]

    def _topic_query(self, file_path: str) -> str:
        """Build a topic query for semantic search from the file's content.

        Uses the strongest evidence chunk of the file (largest text) as a
        natural-language topic probe — no LLM call required.
        """
        try:
            evidence = self._retrieval._evidence
            chunks = [c for c in evidence.values() if c.file_path == file_path]
            if not chunks:
                return ""
            best = max(chunks, key=lambda c: len(c.text or ""))
            text = (best.text or "").strip()
            if len(text) < 40:
                return ""
            # First sentence-ish probe (bounded).
            return text[:300].replace("\n", " ")
        except Exception:
            return ""
