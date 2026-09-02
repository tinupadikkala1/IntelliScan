"""Citation builder — converts retrieval results into persisted citation records.

Every citation carries the exact evidence location (source label/index,
char offsets, timestamps, modality) so the UI can invoke EvidenceNavigator
without fabricating locations (Batch 4 §22).
"""

from __future__ import annotations

import logging
from typing import List

from .models import CitationRecord

logger = logging.getLogger(__name__)


class CitationBuilder:
    """Builds CitationRecord lists from retrieval result objects/dicts."""

    @staticmethod
    def from_results(results, max_citations: int = 8, scope=None) -> List[CitationRecord]:
        citations: List[CitationRecord] = []
        seen: set = set()
        for r in results:
            path = getattr(r, "file_path", None) or (r.get("file_path") if isinstance(r, dict) else "")
            source = getattr(r, "source_label", None) or (r.get("source_label") if isinstance(r, dict) else "")
            text = getattr(r, "text", None) or (r.get("text") if isinstance(r, dict) else "")
            chunk_id = getattr(r, "chunk_id", None) or (r.get("chunk_id") if isinstance(r, dict) else "")
            score = getattr(r, "score", 0.0) or (r.get("score", 0.0) if isinstance(r, dict) else 0.0)

            key = (chunk_id or (path, source))
            if not path or key in seen:
                continue

            if scope is not None:
                from .scope_manager import ScopeManager
                if not ScopeManager.path_in_scope(path, scope):
                    continue

            seen.add(key)


            record = CitationRecord(
                chunk_id=chunk_id or "",
                file_path=path,
                source_label=source or "",
                source_index=int(getattr(r, "source_index", 0) or 0)
                if not isinstance(r, dict) else int(r.get("source_index", 0) or 0),
                source_type=getattr(r, "source_type", "") or (r.get("source_type", "") if isinstance(r, dict) else ""),
                char_start=int(getattr(r, "char_start", 0) or 0)
                if not isinstance(r, dict) else int(r.get("char_start", 0) or 0),
                char_end=int(getattr(r, "char_end", 0) or 0)
                if not isinstance(r, dict) else int(r.get("char_end", 0) or 0),
                timestamp_start=float(getattr(r, "timestamp_start", 0.0) or 0.0)
                if not isinstance(r, dict) else float(r.get("timestamp_start", 0.0) or 0.0),
                timestamp_end=float(getattr(r, "timestamp_end", 0.0) or 0.0)
                if not isinstance(r, dict) else float(r.get("timestamp_end", 0.0) or 0.0),
                snippet=(text[:200] + "..." if text and len(text) > 200 else text or ""),
                score=float(score or 0.0),
                modality=getattr(r, "modality", "document") or (r.get("modality", "document") if isinstance(r, dict) else "document"),
            )
            citations.append(record)
            if len(citations) >= max_citations:
                break
        return citations
