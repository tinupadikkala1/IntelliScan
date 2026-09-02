"""Vector Engine using FAISS for similarity search.

Manages a FAISS index for storing and searching embedding vectors.
Supports add, search, save, load, and remove operations.
"""

from __future__ import annotations

import logging
import os
import pickle
import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple

import faiss
import numpy as np

from .config import EMBEDDING_DIM, SIMILARITY_THRESHOLD, TOP_K_DEFAULT

logger = logging.getLogger(__name__)


def lock_required(func):
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return func(self, *args, **kwargs)
    return wrapper


@dataclass
class SearchResult:
    """A single search result from the vector index."""
    chunk_id: str
    score: float
    rank: int = 0



class VectorEngine:
    """Manages FAISS vector index for semantic similarity search.

    Uses an inner-product (cosine similarity on normalized vectors) index
    with an ID map for tracking chunk associations.
    """

    def __init__(self, dimension: int = EMBEDDING_DIM, index_path: Optional[str] = None) -> None:
        """Initialize the vector engine.

        Args:
            dimension: Vector dimension (must match embedding model output).
            index_path: Path to load/save the FAISS index. If None, in-memory only.
        """
        self._lock = threading.RLock()
        self._dimension = dimension
        self._index_path = index_path
        self._id_map_path = f"{index_path}.ids" if index_path else None

        # chunk_id -> internal index position mapping
        self._chunk_ids: List[str] = []

        # Create FAISS index (L2 distance, we normalize vectors for cosine sim)
        self._index = faiss.IndexFlatIP(dimension)

        # Try to load existing index
        if index_path and os.path.exists(index_path):
            self._load()

    @property
    def size(self) -> int:
        """Return the number of vectors in the index."""
        with self._lock:
            return self._index.ntotal

    @property
    def dimension(self) -> int:
        """Return the vector dimension."""
        return self._dimension

    @lock_required
    def list_chunk_ids(self) -> List[str]:
        """Return a copy of all chunk IDs currently in the index.

        Returns:
            List of chunk_id strings in index order.
        """
        return list(self._chunk_ids)

    @lock_required
    def add(self, chunk_id: str, vector: np.ndarray) -> bool:
        """Add a single vector to the index.

        Args:
            chunk_id: Unique identifier for the chunk.
            vector: Numpy array of shape (dimension,).

        Returns:
            True if added successfully, False otherwise.
        """
        try:
            if vector is None or vector.shape[0] != self._dimension:
                logger.error(
                    "Invalid vector shape for chunk %s: expected %d, got %s",
                    chunk_id[:8],
                    self._dimension,
                    vector.shape if vector is not None else None,
                )
                return False

            # Normalize for cosine similarity
            vec = vector.reshape(1, -1).astype(np.float32)
            faiss.normalize_L2(vec)

            self._index.add(vec)
            self._chunk_ids.append(chunk_id)
            return True
        except Exception as e:
            logger.error("Failed to add vector for chunk %s: %s", chunk_id[:8], e)
            return False

    @lock_required
    def add_batch(self, chunk_ids: List[str], vectors: np.ndarray) -> int:
        """Add a batch of vectors to the index.

        Args:
            chunk_ids: List of unique chunk identifiers.
            vectors: Numpy array of shape (n, dimension).

        Returns:
            Number of vectors successfully added.
        """
        try:
            if vectors.shape[1] != self._dimension:
                logger.error(
                    "Batch vector dimension mismatch: expected %d, got %d",
                    self._dimension,
                    vectors.shape[1],
                )
                return 0

            # Normalize all vectors
            vecs = vectors.astype(np.float32)
            faiss.normalize_L2(vecs)

            self._index.add(vecs)
            self._chunk_ids.extend(chunk_ids)
            logger.info("Added batch of %d vectors (total: %d)", len(chunk_ids), self.size)
            return len(chunk_ids)
        except Exception as e:
            logger.error("Failed to add batch: %s", e)
            return 0

    @lock_required
    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = TOP_K_DEFAULT,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> List[SearchResult]:
        """Search for similar vectors.

        Args:
            query_vector: Query vector of shape (dimension,).
            top_k: Maximum number of results to return.
            threshold: Minimum similarity score to include.

        Returns:
            List of SearchResult ordered by score (highest first).
        """
        if self._index.ntotal == 0:
            logger.debug("Search on empty index, returning no results")
            return []

        try:
            # Normalize query
            vec = query_vector.reshape(1, -1).astype(np.float32)
            faiss.normalize_L2(vec)

            # Search
            k = min(top_k, self._index.ntotal)
            scores, indices = self._index.search(vec, k)

            results: List[SearchResult] = []
            for rank, (score, idx) in enumerate(zip(scores[0], indices[0])):
                if idx < 0 or idx >= len(self._chunk_ids):
                    continue
                if score < threshold:
                    continue
                results.append(SearchResult(
                    chunk_id=self._chunk_ids[idx],
                    score=float(score),
                    rank=rank,
                ))

            logger.debug(
                "Search returned %d results (top_k=%d, threshold=%.2f)",
                len(results),
                top_k,
                threshold,
            )
            return results
        except Exception as e:
            logger.error("Search failed: %s", e)
            return []

    @lock_required
    def remove_by_chunk_ids(self, chunk_ids_to_remove: set) -> int:
        """Remove vectors by chunk IDs (rebuilds index).

        Args:
            chunk_ids_to_remove: Set of chunk IDs to remove.

        Returns:
            Number of vectors removed.
        """
        if not chunk_ids_to_remove:
            return 0

        try:
            # Find indices to keep
            keep_indices = []
            new_chunk_ids = []
            for i, cid in enumerate(self._chunk_ids):
                if cid not in chunk_ids_to_remove:
                    keep_indices.append(i)
                    new_chunk_ids.append(cid)

            removed_count = len(self._chunk_ids) - len(new_chunk_ids)
            if removed_count == 0:
                return 0

            # Rebuild index with remaining vectors
            if keep_indices:
                vectors = np.zeros((len(keep_indices), self._dimension), dtype=np.float32)
                for new_i, old_i in enumerate(keep_indices):
                    vectors[new_i] = self._index.reconstruct(old_i)

                self._index = faiss.IndexFlatIP(self._dimension)
                self._index.add(vectors)
            else:
                self._index = faiss.IndexFlatIP(self._dimension)

            self._chunk_ids = new_chunk_ids
            logger.info("Removed %d vectors, %d remaining", removed_count, self.size)
            return removed_count
        except Exception as e:
            logger.error("Failed to remove vectors: %s", e)
            return 0

    @lock_required
    def save(self) -> bool:
        """Save index to disk.

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self._index_path:
            logger.warning("No index path configured, cannot save")
            return False

        try:
            os.makedirs(os.path.dirname(self._index_path), exist_ok=True)
            faiss.write_index(self._index, self._index_path)

            with open(self._id_map_path, "wb") as f:
                pickle.dump(self._chunk_ids, f)

            logger.info("Saved vector index (%d vectors) to %s", self.size, self._index_path)
            return True
        except Exception as e:
            logger.error("Failed to save index: %s", e)
            return False

    @lock_required
    def _load(self) -> bool:
        """Load index from disk."""
        try:
            if os.path.exists(self._index_path):
                self._index = faiss.read_index(self._index_path)
                logger.info("Loaded FAISS index with %d vectors", self._index.ntotal)

            if self._id_map_path and os.path.exists(self._id_map_path):
                with open(self._id_map_path, "rb") as f:
                    self._chunk_ids = pickle.load(f)
                logger.info("Loaded %d chunk ID mappings", len(self._chunk_ids))

            return True
        except Exception as e:
            logger.error("Failed to load index: %s", e)
            self._index = faiss.IndexFlatIP(self._dimension)
            self._chunk_ids = []
            return False

    @lock_required
    def clear(self) -> None:
        """Clear the entire index."""
        self._index = faiss.IndexFlatIP(self._dimension)
        self._chunk_ids = []
        logger.info("Vector index cleared")
