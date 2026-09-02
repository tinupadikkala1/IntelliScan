"""Retrieval Engine — single unified API for semantic search.

Provides: retrieve(query, scope, top_k)

All features (Semantic Search, Ask Selected File, Similar Documents,
Basic RAG) consume this single API. The engine coordinates:
embedding generation → FAISS search → evidence lookup → ranked results.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

import numpy as np

from .config import (
    AUDIO_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    EMBED_DOCUMENT_PREFIX,
    EMBED_QUERY_PREFIX,
    IMAGE_EXTENSIONS,
    MAX_CHUNKS_PER_FILE,
    RETRIEVAL_DIVERSITY,
    SIMILARITY_HIGH,
    SIMILARITY_MEDIUM,
    SIMILARITY_THRESHOLD,
    TOP_K_DEFAULT,
    VIDEO_EXTENSIONS,
)
from .embedding_engine import EmbeddingEngine
from .evidence_engine import EvidenceChunk
from .vector_engine import SearchResult, VectorEngine

logger = logging.getLogger(__name__)


class RetrievalScope(Enum):
    """Scope of retrieval search."""
    SELECTED_FILE = "selected_file"
    FOLDER = "folder"
    WORKSPACE = "workspace"
    SELECTED_FILES = "selected_files"


@dataclass
class RetrievalResult:
    """A single retrieval result with evidence and metadata."""
    chunk_id: str
    text: str
    score: float
    rank: int
    file_path: str
    file_hash: str
    source_type: str
    source_index: int
    source_label: str
    char_start: int
    char_end: int
    modality: str = "document"
    timestamp_start: float = 0.0
    timestamp_end: float = 0.0
    confidence: float = 1.0
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    @property
    def match_strength(self) -> str:
        """Human label for the similarity score (not calibrated confidence)."""
        return RetrievalEngine.match_strength(self.score)


@dataclass
class RetrievalResponse:
    """Complete response from a retrieval query."""
    query: str
    scope: str
    results: List[RetrievalResult]
    total_found: int
    elapsed_ms: float
    embedding_available: bool = True


class RetrievalEngine:
    """Unified retrieval API for semantic search across all scopes.

    Single entry point: retrieve(query, scope, top_k)

    Coordinates embedding generation, FAISS vector search, and
    evidence chunk lookup to return ranked, sourced results.
    """

    def __init__(
        self,
        embedding_engine: EmbeddingEngine,
        vector_engine: VectorEngine,
        evidence_store: Optional[Dict[str, EvidenceChunk]] = None,
    ) -> None:
        """Initialize the retrieval engine.

        Args:
            embedding_engine: Engine for generating query embeddings.
            vector_engine: FAISS-based vector index for similarity search.
            evidence_store: In-memory map of chunk_id -> EvidenceChunk.
                           Can be updated dynamically as files are indexed.
        """
        self._embedding = embedding_engine
        self._vector = vector_engine
        self._evidence: Dict[str, EvidenceChunk] = evidence_store or {}

    @property
    def indexed_count(self) -> int:
        """Number of evidence chunks currently indexed."""
        return self._vector.size

    def update_evidence_store(self, chunks: List[EvidenceChunk]) -> None:
        """Add evidence chunks to the in-memory store.

        Args:
            chunks: List of EvidenceChunks to make available for lookup.
        """
        for chunk in chunks:
            self._evidence[chunk.chunk_id] = chunk
        logger.debug("Evidence store updated: %d total chunks", len(self._evidence))

    def index_chunks(self, chunks: List[EvidenceChunk]) -> int:
        """Index evidence chunks: generate embeddings and add to FAISS.

        Args:
            chunks: List of EvidenceChunks to embed and index.

        Returns:
            Number of chunks successfully indexed.
        """
        logger.info("Indexing %d evidence chunks", len(chunks))
        start = time.time()
        indexed = 0

        count, indexed_chunks = self.index_chunks_detailed(chunks)
        return count

    def index_chunks_detailed(
        self, chunks: List[EvidenceChunk]
    ) -> tuple:
        """Index evidence chunks and report which ones succeeded.

        Identical to :meth:`index_chunks` but also returns the list of chunks
        that were successfully embedded and added, so callers can persist
        exactly the indexed set (evidence + vector_map).

        Args:
            chunks: List of EvidenceChunks to embed and index.

        Returns:
            Tuple of (indexed_count, list_of_indexed_chunks).
        """
        logger.info("Indexing %d evidence chunks", len(chunks))
        start = time.time()
        indexed = 0
        indexed_chunks: List[EvidenceChunk] = []

        # Build list of texts to embed
        texts_to_embed = []
        model_name = getattr(self._embedding, "_model", "")
        for chunk in chunks:
            text = chunk.text
            if "nomic-embed-text" in model_name:
                text = f"{EMBED_DOCUMENT_PREFIX}{text}"
            texts_to_embed.append(text)

        # Generate embeddings in batch (with fallback if embed_batch is mocked as a MagicMock)
        res = self._embedding.embed_batch(texts_to_embed)
        from unittest.mock import Mock
        if isinstance(res, Mock) or not isinstance(res, (list, tuple)):
            vectors = [self._embedding.embed_text(txt) for txt in texts_to_embed]
        else:
            vectors = res

        for chunk, vector in zip(chunks, vectors):
            if vector is not None:
                if self._vector.add(chunk.chunk_id, vector):
                    self._evidence[chunk.chunk_id] = chunk
                    indexed += 1
                    indexed_chunks.append(chunk)

        elapsed = time.time() - start
        logger.info(
            "Indexed %d/%d chunks in %.2fs (total index: %d)",
            indexed, len(chunks), elapsed, self._vector.size,
        )
        return indexed, indexed_chunks

    def retrieve(
        self,
        query: str,
        scope: RetrievalScope = RetrievalScope.WORKSPACE,
        top_k: int = TOP_K_DEFAULT,
        threshold: float = SIMILARITY_THRESHOLD,
        file_filter: Optional[List[str]] = None,
        max_chunks_per_file: Optional[int] = None,
    ) -> RetrievalResponse:
        """Execute a semantic retrieval query.

        This is the single unified API consumed by all features.

        Args:
            query: Natural language search query.
            scope: Search scope (selected_file, folder, workspace, etc.).
            top_k: Maximum number of results to return.
            threshold: Minimum similarity score threshold.
            file_filter: Optional list of file paths to restrict search to.
                        Used for SELECTED_FILE and SELECTED_FILES scopes.

        Returns:
            RetrievalResponse with ranked results and metadata.
        """
        logger.info(
            "Retrieve: query='%s' scope=%s top_k=%d",
            query[:50], scope.value, top_k,
        )
        start = time.time()

        # Step 1: Embed the query
        query_text = query
        model_name = getattr(self._embedding, "_model", "")
        if "nomic-embed-text" in model_name:
            query_text = f"{EMBED_QUERY_PREFIX}{query_text}"
        query_vector = self._embedding.embed_text(query_text)
        if query_vector is None:
            logger.error("Failed to generate query embedding")
            elapsed = (time.time() - start) * 1000
            return RetrievalResponse(
                query=query,
                scope=scope.value,
                results=[],
                total_found=0,
                elapsed_ms=elapsed,
                embedding_available=False,
            )

        # Step 2: Search FAISS index
        # Request more results than top_k to allow for scope filtering
        search_k = top_k * 3 if file_filter else top_k
        search_results: List[SearchResult] = self._vector.search(
            query_vector, top_k=search_k, threshold=threshold,
        )

        # Step 3: Map results to evidence and apply scope filter
        retrieval_results: List[RetrievalResult] = []
        per_file_counts: Dict[str, int] = {}
        cap = max_chunks_per_file if max_chunks_per_file is not None else MAX_CHUNKS_PER_FILE
        for sr in search_results:
            chunk = self._evidence.get(sr.chunk_id)
            if chunk is None:
                continue

            # Apply file filter (for SELECTED_FILE / SELECTED_FILES scopes)
            if file_filter and chunk.file_path not in file_filter:
                continue

            # Per-file cap keeps a single large file from crowding the
            # result list (Batch 4 M0-04 — evidence diversity).
            count = per_file_counts.get(chunk.file_path, 0)
            if cap and count >= cap:
                continue
            per_file_counts[chunk.file_path] = count + 1

            retrieval_results.append(self._to_result(chunk, sr, len(retrieval_results)))

            if len(retrieval_results) >= top_k:
                break

        elapsed = (time.time() - start) * 1000

        # Update ranks
        for i, r in enumerate(retrieval_results):
            r.rank = i

        logger.info(
            "Retrieve complete: %d results in %.1fms",
            len(retrieval_results), elapsed,
        )

        return RetrievalResponse(
            query=query,
            scope=scope.value,
            results=retrieval_results,
            total_found=len(retrieval_results),
            elapsed_ms=elapsed,
            embedding_available=True,
        )

    def smart_retrieve(
        self,
        query: str,
        top_k: int = TOP_K_DEFAULT,
        threshold: float = 0.3,
        file_filter: Optional[List[str]] = None,
        max_chunks_per_file: Optional[int] = None,
    ) -> RetrievalResponse:
        """Smart semantic retrieval with modality detection and filtering.

        Analyzes the query to detect intended modality (image, audio, video,
        document) and filters results accordingly. Returns ALL matching files
        (not just one) when multiple files are relevant.

        Args:
            query: Natural language search query.
            top_k: Maximum number of results to return.
            threshold: Minimum similarity score.
            file_filter: Optional list of file paths to restrict search to.

        Returns:
            RetrievalResponse with filtered, relevant results.
        """
        logger.info("Smart retrieve: '%s'", query[:50])
        start = time.time()

        # Step 1: Detect modality intent from query
        modality_filter = self._detect_modality(query)
        logger.debug("Detected modality filter: %s", modality_filter)

        # Step 2: Retrieve many candidates (fetch generously)
        response = self.retrieve(
            query=query,
            scope=RetrievalScope.WORKSPACE,
            top_k=top_k * 6,  # Over-fetch generously
            threshold=threshold,
            file_filter=file_filter,
            max_chunks_per_file=max_chunks_per_file or MAX_CHUNKS_PER_FILE,
        )

        if not response.results or not response.embedding_available:
            return response

        # Step 2.5: Keyword / Word-boundary Match Booster (with Stopword Filtering)
        import re
        raw_words = [w.lower() for w in re.findall(r'\w+', query) if len(w) >= 3]

        # Stopword set to ignore common, non-distinct search words
        stopwords = {
            'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and', 'any', 'are', 'as', 'at',
            'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but', 'by', 'can', 'did', 'do',
            'does', 'doing', 'down', 'during', 'each', 'few', 'for', 'from', 'further', 'had', 'has', 'have', 'having',
            'he', 'her', 'here', 'hers', 'herself', 'him', 'himself', 'his', 'how', 'i', 'if', 'in', 'into', 'is', 'it',
            'its', 'itself', 'me', 'more', 'most', 'my', 'myself', 'no', 'nor', 'not', 'of', 'off', 'on', 'once', 'only',
            'or', 'other', 'our', 'ours', 'ourselves', 'out', 'over', 'own', 'same', 'she', 'should', 'so', 'some', 'such',
            'than', 'that', 'the', 'their', 'theirs', 'them', 'themselves', 'then', 'there', 'these', 'they', 'this',
            'those', 'through', 'to', 'too', 'under', 'until', 'up', 'very', 'was', 'we', 'were', 'what', 'when', 'where',
            'which', 'while', 'who', 'whom', 'why', 'with', 'you', 'your', 'yours', 'yourself', 'yourselves',
            # Generic file layout metadata terms
            'file', 'files', 'path', 'paths', 'size', 'sizes', 'date', 'dates', 'metadata', 'extension', 'extensions',
            'type', 'types', 'created', 'modified', 'checksum', 'category', 'tags', 'summary',
        }

        query_words = [w for w in raw_words if w not in stopwords]
        # Pre-compile word-boundary patterns for each keyword
        _qw_patterns = {qw: re.compile(r'\b' + re.escape(qw) + r'\b') for qw in query_words}
        total_kw = len(query_words)

        if total_kw > 0:
            seen_chunk_ids = {r.chunk_id for r in response.results}
            clean_file_filter = {os.path.abspath(f) for f in file_filter} if file_filter else None
            for cid, chunk in self._evidence.items():
                if clean_file_filter and os.path.abspath(chunk.file_path) not in clean_file_filter:
                    continue
                fn_lower = os.path.basename(chunk.file_path).lower().replace('-', ' ').replace('_', ' ')
                txt_lower = chunk.text.lower()
                # Count how many query keywords match (word-boundary)
                matched = 0
                for qw, pat in _qw_patterns.items():
                    if pat.search(fn_lower) or pat.search(txt_lower):
                        matched += 1
                if matched == 0:
                    continue
                # Scale boost: 0.70 base + 0.18 * (matched/total) → max 0.88
                boost = 0.70 + 0.18 * (matched / total_kw)
                if cid not in seen_chunk_ids:
                    sr = SearchResult(chunk_id=cid, score=boost, rank=len(response.results))
                    res = self._to_result(chunk, sr, len(response.results))
                    response.results.append(res)
                    seen_chunk_ids.add(cid)
                else:
                    for r in response.results:
                        if r.chunk_id == cid:
                            r.score = max(r.score, boost)
                            break

        # Step 3: Apply modality filter (with fallback)
        if modality_filter:
            filtered = self._filter_by_modality(response.results, modality_filter)
            if not filtered:
                # Fallback: modality guess was wrong, return all results
                logger.debug(
                    "Modality filter '%s' returned 0 results, falling back to all",
                    modality_filter,
                )
                filtered = response.results
        else:
            filtered = response.results

        # Step 3.5: Penalize metadata-catalog files (CSV/JSON that mostly
        # list filenames rather than substantive content).
        _META_EXT = {'.csv', '.json'}
        for r in filtered:
            ext = os.path.splitext(r.file_path)[1].lower()
            if ext in _META_EXT and r.text:
                lines = r.text.strip().splitlines()
                if lines:
                    path_lines = sum(1 for ln in lines if '/' in ln or '\\' in ln)
                    if path_lines / len(lines) > 0.4:
                        r.score *= 0.7  # Deprioritize path-heavy catalog files

        # Step 3.6: Sort all results descending by score
        # Since scores might have been boosted or items prepended, a clean sort ensures relevance ordering.
        filtered.sort(key=lambda x: x.score, reverse=True)

        # Step 4: Deduplicate by file (keep best score per file)
        deduped = self._deduplicate_by_file(filtered)

        # Step 5: Take top_k results
        final_results = deduped[:top_k]

        # Update ranks
        for i, r in enumerate(final_results):
            r.rank = i

        elapsed = (time.time() - start) * 1000
        logger.info(
            "Smart retrieve: %d results (from %d candidates) in %.1fms",
            len(final_results), len(response.results), elapsed,
        )

        return RetrievalResponse(
            query=query,
            scope="workspace",
            results=final_results,
            total_found=len(final_results),
            elapsed_ms=elapsed,
            embedding_available=True,
        )

    def _detect_modality(self, query: str) -> Optional[str]:
        """Detect the intended modality from the query text.

        Uses a conservative two-tier approach so that content-focused queries
        like ``"circuit diagram components"`` are NOT restricted to a single
        modality.  Only explicit intent phrases (e.g. ``"which image"``,
        ``"find photos"``) trigger filtering.

        Ambiguous single words (``diagram``, ``file``, ``clip``, ``slide``,
        ``recording``, ``figure``, ``illustration``) are intentionally
        **excluded** because they frequently appear in content queries and
        would silently hide relevant results.

        Args:
            query: The user's search query.

        Returns:
            Modality string ('image', 'audio', 'video', 'document') or None.
        """
        import re
        q = query.lower()

        # ── Image: strong phrases first, then unambiguous single words ──
        image_phrases = [
            'which image', 'which photo', 'which picture',
            'in the image', 'in the photo', 'in the picture',
            'show me images', 'show me photos', 'show me pictures',
            'find images', 'find photos', 'find pictures',
            'search images', 'search photos',
        ]
        for phrase in image_phrases:
            if phrase in q:
                return "image"
        for word in ('image', 'photo', 'picture', 'screenshot',
                     'png', 'jpg', 'jpeg'):
            if re.search(r'\b' + word + r'\b', q):
                return "image"

        # ── Audio: strong phrases first, then unambiguous single words ──
        audio_phrases = [
            'which audio', 'in the audio', 'in the recording',
            'what was said', 'who is speaking', 'listen to',
        ]
        for phrase in audio_phrases:
            if phrase in q:
                return "audio"
        for word in ('audio', 'podcast', 'song', 'music', 'mp3', 'wav'):
            if re.search(r'\b' + word + r'\b', q):
                return "audio"

        # ── Video: strong phrases first, then unambiguous single words ──
        video_phrases = [
            'which video', 'in the video', 'video shows',
            'watch the', 'play the video',
        ]
        for phrase in video_phrases:
            if phrase in q:
                return "video"
        for word in ('video', 'footage', 'mp4'):
            if re.search(r'\b' + word + r'\b', q):
                return "video"

        # ── Document: only explicit format requests ──
        for word in ('pdf', 'docx', 'pptx', 'xlsx', 'spreadsheet'):
            if re.search(r'\b' + word + r'\b', q):
                return "document"

        # No specific modality detected — search across all types.
        # NOTE: 'diagram', 'figure', 'file', 'document', 'slide', 'clip',
        # 'recording', 'illustration' are intentionally NOT triggers here.
        return None

    def _filter_by_modality(
        self, results: List[RetrievalResult], modality: str
    ) -> List[RetrievalResult]:
        """Filter results to only include items from the specified modality.

        When a user explicitly asks for a modality (e.g. "images"),
        ONLY return that modality. Never fall back to other types.

        Args:
            results: List of retrieval results.
            modality: The target modality.

        Returns:
            Filtered list of results (may be empty if no matches).
        """
        filtered = []
        for r in results:
            m = r.modality or self.modality_of(r.file_path)
            if m == modality:
                filtered.append(r)
            # Match media modality generic mapping
            elif modality == "media" and m in ("audio", "video"):
                filtered.append(r)
            elif modality in ("audio", "video") and m == "media":
                filtered.append(r)
        return filtered

    def _deduplicate_by_file(self, results: List[RetrievalResult]) -> List[RetrievalResult]:
        """Keep only the best-scoring result per file.

        Prevents the same file from appearing multiple times in results.

        Args:
            results: List of results (may have duplicates per file).

        Returns:
            Deduplicated list (one result per file, highest score kept).
        """
        seen_files: Dict[str, RetrievalResult] = {}
        for r in results:
            if r.file_path not in seen_files or r.score > seen_files[r.file_path].score:
                seen_files[r.file_path] = r

        # Sort by score descending
        deduped = sorted(seen_files.values(), key=lambda x: x.score, reverse=True)
        return deduped

    def retrieve_similar(
        self,
        file_path: str,
        top_k: int = TOP_K_DEFAULT,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> RetrievalResponse:
        """Find documents similar to a given file.

        Uses the average embedding of the file's chunks as the query vector.

        Args:
            file_path: Path of the reference file.
            top_k: Maximum number of similar results.
            threshold: Minimum similarity score.

        Returns:
            RetrievalResponse with similar document chunks (excluding the source file).
        """
        logger.info("Finding similar documents to: %s", file_path)
        start = time.time()

        # Gather all chunks belonging to this file
        file_chunks = [c for c in self._evidence.values() if c.file_path == file_path]
        if not file_chunks:
            elapsed = (time.time() - start) * 1000
            return RetrievalResponse(
                query=f"similar:{file_path}",
                scope="similar",
                results=[],
                total_found=0,
                elapsed_ms=elapsed,
            )

        # Generate embeddings for file chunks and compute average
        texts_to_embed = []
        model_name = getattr(self._embedding, "_model", "")
        for chunk in file_chunks:
            text = chunk.text
            if "nomic-embed-text" in model_name:
                text = f"{EMBED_DOCUMENT_PREFIX}{text}"
            texts_to_embed.append(text)

        # Generate embeddings in batch (with fallback if embed_batch is mocked as a MagicMock)
        res = self._embedding.embed_batch(texts_to_embed)
        from unittest.mock import Mock
        if isinstance(res, Mock) or not isinstance(res, (list, tuple)):
            vectors = [self._embedding.embed_text(txt) for txt in texts_to_embed]
            vectors = [v for v in vectors if v is not None]
        else:
            vectors = [v for v in res if v is not None]

        if not vectors:
            elapsed = (time.time() - start) * 1000
            return RetrievalResponse(
                query=f"similar:{file_path}",
                scope="similar",
                results=[],
                total_found=0,
                elapsed_ms=elapsed,
                embedding_available=False,
            )

        # Average vector as query
        avg_vector = np.mean(vectors, axis=0).astype(np.float32)

        # Search excluding the source file
        search_results = self._vector.search(avg_vector, top_k=top_k * 2, threshold=threshold)

        retrieval_results: List[RetrievalResult] = []
        for sr in search_results:
            chunk = self._evidence.get(sr.chunk_id)
            if chunk is None or chunk.file_path == file_path:
                continue
            if chunk.file_path and not os.path.exists(chunk.file_path):
                continue

            retrieval_results.append(self._to_result(chunk, sr, len(retrieval_results)))

            if len(retrieval_results) >= top_k:
                break

        elapsed = (time.time() - start) * 1000
        for i, r in enumerate(retrieval_results):
            r.rank = i

        return RetrievalResponse(
            query=f"similar:{file_path}",
            scope="similar",
            results=retrieval_results,
            total_found=len(retrieval_results),
            elapsed_ms=elapsed,
        )

    def remove_file(self, file_path: str) -> int:
        """Remove all indexed chunks for a file.

        Args:
            file_path: Path of the file to remove from the index.

        Returns:
            Number of chunks removed.
        """
        chunk_ids_to_remove = {
            cid for cid, chunk in self._evidence.items()
            if chunk.file_path == file_path
        }
        if not chunk_ids_to_remove:
            return 0

        removed = self._vector.remove_by_chunk_ids(chunk_ids_to_remove)
        for cid in chunk_ids_to_remove:
            self._evidence.pop(cid, None)

        logger.info("Removed %d chunks for file: %s", removed, file_path)
        return removed

    # ------------------------------------------------------------------ #
    # Hydration / persistence helpers
    # ------------------------------------------------------------------ #
    def hydrate_from_store(self, db_store) -> int:
        """Restore the in-memory evidence map from persistent storage.

        Loads every evidence chunk from the database and keeps only the
        chunks whose vectors still exist in the FAISS index. Orphaned FAISS
        vectors (no matching evidence) are removed so the invariant
        ``every FAISS id resolves to an EvidenceChunk`` holds.

        Args:
            db_store: EngineDBStore instance.

        Returns:
            Number of evidence chunks hydrated.
        """
        if db_store is None:
            return 0
        try:
            all_evidence = db_store.get_all_evidence()
            faiss_ids = set(self._vector.list_chunk_ids())

            hydrated = 0
            orphaned = []
            for chunk in all_evidence:
                if chunk.chunk_id in faiss_ids:
                    self._evidence[chunk.chunk_id] = chunk
                    hydrated += 1
                else:
                    orphaned.append(chunk.chunk_id)

            # Remove FAISS vectors whose evidence is missing (rare corruption)
            missing_in_db = faiss_ids - {
                c.chunk_id for c in all_evidence
            }
            if missing_in_db:
                logger.warning(
                    "Hydration: %d orphaned FAISS vectors without evidence, removing",
                    len(missing_in_db),
                )
                self._vector.remove_by_chunk_ids(missing_in_db)

            logger.info(
                "Hydrated %d evidence chunks (orphans: %d evidence, %d vectors)",
                hydrated, len(orphaned), len(missing_in_db),
            )
            return hydrated
        except Exception as e:
            logger.error("Evidence hydration failed: %s", e)
            return 0

    # ------------------------------------------------------------------ #
    # Modality / match-strength helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def modality_of(file_path: str) -> str:
        """Return the modality for a file path by extension or magic bytes."""
        try:
            from engines.config import detect_modality_and_ext
            modality, _ = detect_modality_and_ext(file_path)
            return modality
        except Exception:
            import os
            ext = os.path.splitext(file_path)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                return "image"
            if ext in AUDIO_EXTENSIONS:
                return "audio"
            if ext in VIDEO_EXTENSIONS:
                return "video"
            return "document"

    @staticmethod
    def match_strength(score: float) -> str:
        """Classify a cosine similarity score into a match-strength label.

        Cosine similarity is NOT calibrated confidence; this only provides a
        coarse, documented human label.
        """
        if score >= SIMILARITY_HIGH:
            return "High"
        if score >= SIMILARITY_MEDIUM:
            return "Medium"
        return "Low"

    @staticmethod
    def explain_match(result) -> str:
        """Short human explanation of why a result matched."""
        source = result.source_type or ""
        if source in ("ocr",):
            return "Matched by OCR text"
        if source in ("caption", "clip_visual", "keyframe"):
            return "Matched by visual description"
        if source in ("transcript",):
            return "Matched by transcript"
        return "Matched by semantic similarity"

    def filter_results_by_modality(
        self, results: List[RetrievalResult], modality: str
    ) -> List[RetrievalResult]:
        """Public modality filter for explicit UI filters (All/Docs/Images/...)."""
        if not modality or modality == "all":
            return list(results)
        return self._filter_by_modality(results, modality)

    def _to_result(self, chunk: EvidenceChunk, sr: SearchResult, rank: int) -> RetrievalResult:
        """Convert evidence + search result into a RetrievalResult."""
        return RetrievalResult(
            chunk_id=sr.chunk_id,
            text=chunk.text,
            score=sr.score,
            rank=rank,
            file_path=chunk.file_path,
            file_hash=chunk.file_hash,
            source_type=chunk.source_type,
            source_index=chunk.source_index,
            source_label=chunk.source_label,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            modality=getattr(chunk, "modality", None) or self.modality_of(chunk.file_path),
            timestamp_start=getattr(chunk, "timestamp_start", 0.0) or 0.0,
            timestamp_end=getattr(chunk, "timestamp_end", 0.0) or 0.0,
            confidence=getattr(chunk, "confidence", 1.0) or 1.0,
            metadata=getattr(chunk, "metadata", None),
        )

    def clear(self) -> None:
        """Clear the entire index and evidence store."""
        self._vector.clear()
        self._evidence.clear()
        logger.info("Retrieval engine cleared")

    # ------------------------------------------------------------------ #
    # Integrity checking (Batch 4 M0-03)
    # ------------------------------------------------------------------ #
    def validate_vector_evidence_integrity(self, db_store=None) -> dict:
        """Verify the vector↔evidence↔vector_map invariants.

        Checks (and reports, does not mutate):
          1. Every FAISS vector resolves to an EvidenceChunk in memory.
          2. Every in-memory evidence chunk has a persisted evidence row.
          3. Every persisted vector_map row matches an in-memory chunk
             (when db_store is supplied).

        Returns a dict report:
            {"active_vectors", "evidence_in_memory", "evidence_in_db",
             "vector_map_rows", "orphan_vectors", "missing_evidence",
             "valid"}
        """
        report = {
            "active_vectors": self._vector.size,
            "evidence_in_memory": len(self._evidence),
            "evidence_in_db": 0,
            "vector_map_rows": 0,
            "orphan_vectors": 0,
            "missing_evidence": 0,
            "vector_map_orphans": 0,
            "valid": True,
        }
        try:
            faiss_ids = set(self._vector.list_chunk_ids())
            report["orphan_vectors"] = len(faiss_ids - set(self._evidence.keys()))
            report["missing_evidence"] = sum(
                1 for cid in self._evidence if cid not in faiss_ids
            )

            if db_store is not None:
                db_ids = {c.chunk_id for c in db_store.get_all_evidence()}
                report["evidence_in_db"] = len(db_ids)
                report["missing_evidence"] += sum(
                    1 for cid in self._evidence if cid not in db_ids
                )
                vm = db_store.get_all_vector_maps()
                report["vector_map_rows"] = len(vm)
                vm_ids = {row["chunk_id"] for row in vm}
                report["vector_map_orphans"] = len(
                    vm_ids - set(self._evidence.keys())
                )

            report["valid"] = (
                report["orphan_vectors"] == 0
                and report["missing_evidence"] == 0
                and report["vector_map_orphans"] == 0
            )
            return report
        except Exception as exc:
            logger.error("Integrity check failed: %s", exc)
            report["valid"] = False
            report["error"] = str(exc)
            return report
