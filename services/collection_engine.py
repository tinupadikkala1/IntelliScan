"""Collection engine — B5-03.

Virtual collections (never moving/copying files):

- **Static** collections hold explicitly added members.
- **Smart** collections derive membership from ``criteria``:

      {"category": "research"}                       category filter
      {"tag": "machine-learning"}                    canonical tag filter
      {"extension": ".pdf"}                          extension filter
      {"folder": "/abs/path"}                        folder prefix filter
      {"semantic_query": "files related to X"}       semantic search (FAISS)

Membership is validated and refreshed against the current index; deleted
files are cleaned through the shared cleanup path. Smart evaluation is
cheap (no LLM) — semantic criteria reuse the retrieval engine.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from .batch5_models import CollectionInfo
from .batch5_store import Batch5Store

logger = logging.getLogger(__name__)


class CollectionEngine:
    """CRUD + smart-criteria evaluation for collections."""

    def __init__(self, store: Batch5Store, retrieval=None, classifier=None, tagger=None) -> None:
        """Args:
            store: Batch5Store.
            retrieval: RetrievalEngine (for semantic criteria).
            classifier: ClassificationEngine (category criteria).
            tagger: TaggingEngine (tag criteria).
        """
        self._store = store
        self._retrieval = retrieval
        self._classifier = classifier
        self._tagger = tagger

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def create(
        self,
        name: str,
        description: str = "",
        is_smart: bool = False,
        criteria: Optional[dict] = None,
    ) -> int:
        if not name.strip():
            raise ValueError("Collection name cannot be empty")
        return self._store.create_collection(
            name=name.strip(),
            description=description or "",
            is_smart=is_smart,
            criteria=criteria or {},
        )

    def list(self) -> List[CollectionInfo]:
        return self._store.list_collections()

    def get(self, collection_id: int) -> Optional[CollectionInfo]:
        return self._store.get_collection(collection_id)

    def rename(self, collection_id: int, name: str) -> bool:
        if not name.strip():
            raise ValueError("Collection name cannot be empty")
        return self._store.rename_collection(collection_id, name.strip())

    def update_criteria(self, collection_id: int, criteria: dict) -> bool:
        return self._store.update_collection_criteria(collection_id, criteria or {})

    def delete(self, collection_id: int) -> bool:
        return self._store.delete_collection(collection_id)

    # ------------------------------------------------------------------ #
    # Static membership
    # ------------------------------------------------------------------ #
    def add_member(self, collection_id: int, file_path: str) -> bool:
        """Add a static member (deduped by path)."""
        return self._store.add_item(collection_id, os.path.abspath(file_path), source="manual")

    def remove_member(self, collection_id: int, file_path: str) -> bool:
        return self._store.remove_item(collection_id, os.path.abspath(file_path))

    def member_paths(self, collection_id: int) -> List[str]:
        return self._store.collection_paths(collection_id)

    def collections_for_path(self, file_path: str) -> List[int]:
        return self._store.collections_for_path(file_path)

    # ------------------------------------------------------------------ #
    # Smart evaluation
    # ------------------------------------------------------------------ #
    def evaluate_criteria(self, criteria: dict) -> List[str]:
        """Return matching indexed file paths for a smart-criteria dict."""
        if not criteria:
            return []
        candidates = self._all_indexed_paths()
        if not candidates:
            return []

        # Semantic criteria — the only path that may touch FAISS.
        semantic = (criteria.get("semantic_query") or "").strip()
        if semantic and self._retrieval is not None:
            try:
                response = self._retrieval.smart_retrieve(semantic, top_k=200, threshold=0.0)
                semantic_paths = {r.file_path for r in response.results}
                candidates = [p for p in candidates if p in semantic_paths]
            except Exception as exc:
                logger.debug("Semantic criteria failed: %s", exc)
                candidates = []
        if not candidates:
            return []

        result = []
        for path in candidates:
            if self._path_matches(path, criteria):
                result.append(path)
        return result

    def _path_matches(self, path: str, criteria: dict) -> bool:
        """AND semantics across all provided criteria."""
        # Category
        category = criteria.get("category")
        if category:
            cat = self._category_of(path)
            if cat != category:
                return False
        # Canonical tag
        tag = criteria.get("tag")
        if tag:
            tags = self._tags_of(path)
            if tag not in tags:
                return False
        # Extension
        ext = criteria.get("extension")
        if ext:
            if os.path.splitext(path)[1].lower() != str(ext).lower():
                return False
        # Folder prefix
        folder = criteria.get("folder")
        if folder:
            if not path.startswith(os.path.abspath(folder) + os.sep):
                return False
        return True

    def _category_of(self, path: str) -> str:
        if self._classifier is not None:
            cat = self._classifier.category_for_path(path)
            if cat:
                return cat
        # Deterministic fallback.
        from services.classification_engine import category_from_extension
        return category_from_extension(path)

    def _tags_of(self, path: str) -> List[str]:
        if self._tagger is not None:
            return self._tagger.tags_for_path(path)
        return []

    def refresh(self, collection_id: int) -> int:
        """Re-evaluate a smart collection; returns member count.

        Static collections are untouched (their members stay explicit).
        """
        info = self._store.get_collection(collection_id)
        if info is None:
            return 0
        if not info.is_smart:
            return len(self._store.collection_paths(collection_id))
        matches = self.evaluate_criteria(info.criteria)
        # Replace smart membership wholesale (source='criteria').
        self._store.clear_collection_items(collection_id)
        for path in matches:
            self._store.add_item(collection_id, path, source="criteria")
        return len(matches)

    def refresh_all(self) -> dict:
        """Refresh every smart collection; returns {id: member_count}."""
        out = {}
        for info in self._store.list_collections():
            if info.is_smart:
                try:
                    out[info.id] = self.refresh(info.id)
                except Exception as exc:
                    logger.debug("Collection %s refresh failed: %s", info.id, exc)
        return out

    # ------------------------------------------------------------------ #
    def _all_indexed_paths(self) -> List[str]:
        try:
            from services.sqlite_indexer import IndexedFile

            with self._store._session_factory() as session:
                rows = session.query(IndexedFile.absolute_path).all()
                return [r[0] for r in rows]
        except Exception:
            return []
