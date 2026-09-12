"""Embedding Engine for generating vector embeddings via Ollama.

Uses nomic-embed-text model through Ollama's embedding API to convert
text chunks into dense vector representations for semantic search.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

import numpy as np
import requests

from .config import (
    EMBED_BATCH_TIMEOUT,
    EMBED_MAX_RETRIES,
    EMBED_TIMEOUT,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    OLLAMA_BASE_URL,
)

logger = logging.getLogger(__name__)


class EmbeddingEngine:
    """Generates text embeddings using nomic-embed-text via Ollama.

    Converts text strings into fixed-dimension float vectors suitable
    for cosine similarity search in FAISS.
    """

    def __init__(
        self,
        model: str = EMBEDDING_MODEL,
        base_url: str = OLLAMA_BASE_URL,
        dimension: int = EMBEDDING_DIM,
        resources=None,
    ) -> None:
        """Initialize the embedding engine.

        Args:
            model: Name of the embedding model in Ollama.
            base_url: Ollama server base URL.
            dimension: Expected vector dimension.
            resources: Optional AIResourceManager to bound embedding calls.
        """
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._dimension = dimension
        self._embed_url = f"{self._base_url}/api/embed"
        self._resources = resources

    def _ollama_options(self) -> dict:
        """Ollama options from Settings (cpu_threads, gpu offload). Never raises."""
        try:
            from core.config import Config

            from services.compute import ollama_options

            return ollama_options(Config())
        except Exception:
            try:
                from services.compute import inference_options

                return inference_options()
            except Exception:
                return {}

    @property
    def dimension(self) -> int:
        """Return the embedding vector dimension."""
        return self._dimension

    def embed_text(self, text: str) -> Optional[np.ndarray]:
        """Generate embedding vector for a single text string.

        Args:
            text: Input text to embed.

        Returns:
            Numpy array of shape (dimension,) or None on failure.
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding")
            return None

        last_err: Exception | None = None
        for attempt in range(1, EMBED_MAX_RETRIES + 1):
            try:
                start = time.time()
                if self._resources is not None:
                    with self._resources.embedding():
                        response = requests.post(
                            self._embed_url,
                            json={"model": self._model, "input": text, "options": self._ollama_options()},
                            timeout=EMBED_TIMEOUT,
                        )
                else:
                    response = requests.post(
                        self._embed_url,
                        json={"model": self._model, "input": text, "options": self._ollama_options()},
                        timeout=EMBED_TIMEOUT,
                    )
                elapsed = time.time() - start

                if response.status_code != 200:
                    logger.error(
                        "Ollama embed API error (status %d): %s",
                        response.status_code,
                        response.text[:200],
                    )
                    return None

                data = response.json()
                embeddings = data.get("embeddings")
                if not embeddings or len(embeddings) == 0:
                    logger.error("No embeddings returned from Ollama")
                    return None

                vector = np.array(embeddings[0], dtype=np.float32)

                # Update dimension if model returns different size
                # (e.g. nomic 768d -> bge-m3 1024d switch)
                if vector.shape[0] != self._dimension:
                    logger.info(
                        "Embedding dimension %d differs from expected %d, adjusting",
                        vector.shape[0],
                        self._dimension,
                    )
                    self._dimension = vector.shape[0]

                # L2-normalize so FAISS IndexFlatIP inner product == cosine.
                # Matches New Folder Embedder + FileGraphBuilder expectation.
                norm = float(np.linalg.norm(vector))
                if norm > 1e-12:
                    vector = (vector / norm).astype(np.float32)

                logger.debug(
                    "Generated embedding (dim=%d) in %.2fs for text[:%d]",
                    vector.shape[0],
                    elapsed,
                    min(len(text), 50),
                )
                return vector

            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = e
                logger.warning(
                    "Embedding attempt %d/%d failed (%s), retrying",
                    attempt,
                    EMBED_MAX_RETRIES,
                    e,
                )
                if attempt < EMBED_MAX_RETRIES:
                    time.sleep(min(2**attempt, 8))
                    continue
                logger.error("Ollama embedding request failed after retries: %s", e)
                return None
            except Exception as e:
                logger.error("Embedding generation failed: %s", e)
                return None

    def embed_batch(self, texts: List[str]) -> List[Optional[np.ndarray]]:
        """Generate embeddings for a batch of texts.

        Args:
            texts: List of input texts to embed.

        Returns:
            List of numpy arrays (or None for failed items).
        """
        if not texts:
            return []

        logger.info("Embedding batch of %d texts", len(texts))
        start = time.time()
        
        # Track non-empty texts to batch them
        non_empty_indices = []
        non_empty_texts = []
        for idx, text in enumerate(texts):
            if text and text.strip():
                non_empty_indices.append(idx)
                non_empty_texts.append(text)

        results: List[Optional[np.ndarray]] = [None] * len(texts)

        if not non_empty_texts:
            return results

        try:
            # Send batch request to Ollama's embed API
            if self._resources is not None:
                with self._resources.embedding():
                    response = requests.post(
                        self._embed_url,
                        json={"model": self._model, "input": non_empty_texts, "options": self._ollama_options()},
                        timeout=EMBED_BATCH_TIMEOUT,
                    )
            else:
                response = requests.post(
                    self._embed_url,
                    json={"model": self._model, "input": non_empty_texts, "options": self._ollama_options()},
                    timeout=EMBED_BATCH_TIMEOUT,
                )

            if response.status_code == 200:
                data = response.json()
                embeddings = data.get("embeddings")
                if embeddings and len(embeddings) == len(non_empty_texts):
                    for batch_idx, emb in enumerate(embeddings):
                        orig_idx = non_empty_indices[batch_idx]
                        vector = np.array(emb, dtype=np.float32)

                        # Adjust dimension if mismatch
                        if vector.shape[0] != self._dimension:
                            self._dimension = vector.shape[0]

                        n = float(np.linalg.norm(vector))
                        if n > 1e-12:
                            vector = (vector / n).astype(np.float32)

                        results[orig_idx] = vector
                    
                    elapsed = time.time() - start
                    success_count = sum(1 for v in results if v is not None)
                    logger.info(
                        "Batch embedding complete: %d/%d successful in %.2fs",
                        success_count,
                        len(texts),
                        elapsed,
                    )
                    return results
                else:
                    logger.warning("Ollama batch embed response mismatch or empty, falling back to sequential")
            else:
                logger.warning("Ollama batch embed failed (status %d), falling back to sequential", response.status_code)
        except Exception as e:
            logger.warning("Batch embedding request failed: %s, falling back to sequential", e)

        # Sequential fallback
        results = []
        for i, text in enumerate(texts):
            vector = self.embed_text(text)
            results.append(vector)
            if (i + 1) % 10 == 0:
                logger.debug("Embedded %d/%d texts", i + 1, len(texts))

        elapsed = time.time() - start
        success_count = sum(1 for v in results if v is not None)
        logger.info(
            "Batch embedding fallback complete: %d/%d successful in %.2fs",
            success_count,
            len(texts),
            elapsed,
        )
        return results

    def is_available(self) -> bool:
        """Check if the embedding model is available in Ollama.

        Returns:
            True if model is accessible, False otherwise.
        """
        try:
            response = requests.get(
                f"{self._base_url}/api/tags", timeout=5
            )
            if response.status_code != 200:
                return False
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            available = any(self._model in name for name in model_names)
            if not available:
                logger.warning(
                    "Embedding model '%s' not found. Available: %s",
                    self._model,
                    model_names,
                )
            return available
        except Exception as e:
            logger.error("Cannot check Ollama availability: %s", e)
            return False
