"""Saved semantic search manager — B5-09.

Persists re-runnable semantic searches. Re-running always queries the
*current* FAISS/evidence state — saved result lists are never stored as the
source of truth (Batch 5 §13), so newly indexed content automatically
appears when a saved search is re-run.

``search_history`` remains an activity log and is deliberately not converted
into saved searches.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from engines.retrieval_engine import RetrievalEngine, RetrievalScope

from .batch5_models import SavedSearchInfo
from .batch5_store import Batch5Store

logger = logging.getLogger(__name__)


class SavedSearchManager:
    """CRUD + execution of saved semantic searches."""

    def __init__(self, store: Batch5Store, retrieval: RetrievalEngine) -> None:
        self._store = store
        self._retrieval = retrieval

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def create(
        self,
        name: str,
        query: str,
        scope: str = "workspace",
        scope_path: str = "",
        modality: str = "all",
        filters: Optional[dict] = None,
    ) -> int:
        if not name.strip():
            raise ValueError("Saved search name cannot be empty")
        if not query.strip():
            raise ValueError("Saved search query cannot be empty")
        return self._store.create_saved_search(
            name=name.strip(),
            query=query.strip(),
            scope=scope,
            scope_path=scope_path,
            modality=modality,
            filters=filters,
        )

    def list(self) -> List[SavedSearchInfo]:
        return self._store.list_saved_searches()

    def get(self, search_id: int) -> Optional[SavedSearchInfo]:
        return self._store.get_saved_search(search_id)

    def rename(self, search_id: int, name: str) -> bool:
        if not name.strip():
            raise ValueError("Saved search name cannot be empty")
        return self._store.rename_saved_search(search_id, name.strip())

    def update(
        self,
        search_id: int,
        scope: Optional[str] = None,
        scope_path: Optional[str] = None,
        modality: Optional[str] = None,
        filters: Optional[dict] = None,
    ) -> bool:
        return self._store.update_saved_search_config(
            search_id, scope=scope, scope_path=scope_path,
            modality=modality, filters=filters,
        )

    def delete(self, search_id: int) -> bool:
        return self._store.delete_saved_search(search_id)

    # ------------------------------------------------------------------ #
    # Execution — against the CURRENT index
    # ------------------------------------------------------------------ #
    def execute(
        self,
        search_id: int,
        top_k: int = 10,
        threshold: float = 0.3,
    ) -> dict:
        """Run a saved search against the current FAISS state.

        Returns a dict suitable for the semantic-search result list:
            {"query": str, "scope": str, "modality": str, "results": [dict]}
        Raises ValueError for a missing saved search.
        """
        saved = self._store.get_saved_search(search_id)
        if saved is None:
            raise ValueError(f"Saved search {search_id} no longer exists")

        scope = saved.scope or "workspace"
        scope_path = saved.scope_path or ""
        modality = saved.modality or "all"

        # Build the file filter for scoped execution.
        file_filter = None
        if scope == "file" and scope_path:
            file_filter = [os.path.abspath(scope_path)]
        elif scope == "folder" and scope_path:
            folder = os.path.abspath(scope_path)
            file_filter = self._folder_paths(folder)

        try:
            response = self._retrieval.smart_retrieve(
                saved.query,
                top_k=top_k,
                threshold=threshold,
            )
        except Exception as exc:
            logger.error("Saved search %d execution failed: %s", search_id, exc)
            raise

        results = []
        if response.results:
            candidates = response.results
            if modality and modality != "all":
                candidates = self._retrieval.filter_results_by_modality(candidates, modality)
            if file_filter:
                candidates = [r for r in candidates if r.file_path in file_filter]
            for r in candidates[:top_k]:
                results.append({
                    "score": r.score,
                    "text": r.text,
                    "source_label": r.source_label,
                    "source_type": r.source_type,
                    "source_index": r.source_index,
                    "file_path": r.file_path,
                    "modality": r.modality,
                    "timestamp_start": r.timestamp_start,
                    "timestamp_end": r.timestamp_end,
                    "match_strength": r.match_strength,
                })

        self._store.touch_saved_search(search_id)
        return {
            "search_id": search_id,
            "name": saved.name,
            "query": saved.query,
            "scope": scope,
            "scope_path": scope_path,
            "modality": modality,
            "results": results,
        }

    def _folder_paths(self, folder: str) -> List[str]:
        """All indexed evidence file paths under a folder."""
        try:
            evidence = self._retrieval._evidence
            return [
                c.file_path for c in evidence.values()
                if c.file_path.startswith(folder + os.sep)
            ]
        except Exception:
            return []
