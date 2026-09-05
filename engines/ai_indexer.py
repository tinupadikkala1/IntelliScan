"""AI Folder Indexing Engine.

Scans a directory and indexes all supported files for semantic search.
Extracts text from documents, OCR/captions from images, transcriptions
from audio/video, then embeds everything into the FAISS vector index.

This is the core engine behind the "Index Folder for AI" feature.

Persistence: when an EngineDBStore is supplied, evidence chunks and
vector mappings are written to SQLite per file (transactional unit), so
the index survives application restart and can be hydrated at startup.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional, Set

from engines.clip_engine import CLIPEngine
from engines.config import (
    AUDIO_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    IMAGE_EXTENSIONS,
    MIN_FREE_DISK_MB,
    SKIP_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from engines.content_engine import ContentBlock, UniversalContentEngine
from engines.embedding_engine import EmbeddingEngine
from engines.evidence_engine import EvidenceChunk, EvidenceEngine
from engines.retrieval_engine import RetrievalEngine
from engines.vector_engine import VectorEngine

logger = logging.getLogger(__name__)

# Backward-compatible aliases (extension registries now live in config)
_IMAGE_EXT = IMAGE_EXTENSIONS
_AUDIO_EXT = AUDIO_EXTENSIONS
_VIDEO_EXT = VIDEO_EXTENSIONS
_TEXT_EXTRACTABLE = DOCUMENT_EXTENSIONS
_SKIP_EXT = SKIP_EXTENSIONS


@dataclass
class IndexingProgress:
    """Progress update during indexing."""
    current: int
    total: int
    current_file: str
    status: str  # "extracting", "embedding", "done", "error"


@dataclass
class IndexingResult:
    """Result of a folder indexing operation."""
    total_files: int
    indexed_files: int
    skipped_files: int
    total_chunks: int
    errors: List[str]
    unchanged_skipped: int = 0
    no_content_skipped: int = 0



class AIFolderIndexer:
    """Indexes all files in a folder for semantic search.

    Pipeline per file:
    1. Detect modality (text/image/audio/video)
    2. Extract content (text extraction, OCR, captioning, transcription)
    3. Build evidence chunks
    4. Generate embeddings (nomic-embed-text for text, CLIP for images)
    5. Store in FAISS index (+ persist evidence/vector_map when db_store given)

    After indexing, Semantic Search can find any file by content.
    """

    def __init__(
        self,
        retrieval_engine: RetrievalEngine,
        progress_callback: Optional[Callable[[IndexingProgress], None]] = None,
        db_store=None,
        graph_engine=None,
        resources=None,
    ) -> None:
        """Initialize the folder indexer.

        Args:
            retrieval_engine: The retrieval engine to index into.
            progress_callback: Optional callback for progress updates.
            db_store: Optional EngineDBStore for persisting evidence and
                vector mappings (required for restart-safe indexing).
            graph_engine: Optional graph.GraphEngine to extract entities/
                relationships from each indexed file (Batch 4 M7).
            resources: Optional AIResourceManager to bound heavy calls.
        """
        self._retrieval = retrieval_engine
        self._progress_cb = progress_callback
        self._db_store = db_store
        self._graph = graph_engine
        self._resources = resources
        self._content_engine = UniversalContentEngine()
        self._evidence_engine = EvidenceEngine()
        self._clip_engine = CLIPEngine()

    def index_folder(
        self,
        folder_path: str,
        recursive: bool = True,
        cancel_event=None,
    ) -> IndexingResult:
        """Index all supported files in a folder.

        Args:
            folder_path: Path to the folder to index.
            recursive: Whether to scan subdirectories.
            cancel_event: Threading event to check for cancellation.

        Returns:
            IndexingResult with statistics.
        """
        folder_path = os.path.abspath(folder_path)
        logger.info("AI Indexing: scanning '%s' (recursive=%s)", folder_path, recursive)

        # Disk-space safety check before any expensive work.
        try:
            usage = shutil.disk_usage(folder_path)
            free_mb = usage.free / (1024 * 1024)
            if free_mb < MIN_FREE_DISK_MB:
                msg = (
                    f"Insufficient disk space for indexing: {free_mb:.0f} MB free, "
                    f"need at least {MIN_FREE_DISK_MB} MB."
                )
                logger.error(msg)
                return IndexingResult(
                    total_files=0, indexed_files=0, skipped_files=0,
                    total_chunks=0, errors=[msg],
                )
        except OSError as exc:
            logger.warning("Disk space check failed: %s", exc)

        # Discover all files
        files = self._discover_files(folder_path, recursive)
        total = len(files)
        logger.info("AI Indexing: found %d files to process", total)

        indexed = 0
        skipped = 0
        unchanged_skipped = 0
        no_content_skipped = 0
        total_chunks = 0
        errors: List[str] = []

        for i, file_path in enumerate(files):
            # Check cancellation
            if cancel_event and cancel_event.is_set():
                logger.info("AI Indexing: cancelled by user")
                break

            # Progress update
            if self._progress_cb:
                self._progress_cb(IndexingProgress(
                    current=i + 1,
                    total=total,
                    current_file=os.path.basename(file_path),
                    status="extracting",
                ))

            # Check if already indexed and unchanged (verifying SHA-256 file hash)
            abs_path = os.path.abspath(file_path)
            existing = [
                c for c in self._retrieval._evidence.values()
                if c.file_path == abs_path
            ]
            if existing:
                try:
                    current_hash = self._hash_file(abs_path)
                except Exception:
                    current_hash = ""

                stored_hash = getattr(existing[0], "file_hash", "") or ""
                if current_hash and stored_hash and stored_hash == current_hash:
                    skipped += 1
                    unchanged_skipped += 1
                    continue
                elif current_hash and not stored_hash:
                    for c in existing:
                        c.file_hash = current_hash
                    skipped += 1
                    unchanged_skipped += 1
                    continue
                else:
                    # Content modified since last indexing: remove stale evidence & re-index
                    logger.info("File content modified, re-indexing: %s", abs_path)
                    self._remove_file_evidence(abs_path)



            # Index this file transactionally: on failure, clean partial state.
            try:
                chunks_indexed = self._index_file(file_path)
                if chunks_indexed > 0:
                    indexed += 1
                    total_chunks += chunks_indexed
                else:
                    skipped += 1
                    no_content_skipped += 1
            except Exception as e:
                errors.append(f"{os.path.basename(file_path)}: {e}")
                logger.error("AI Indexing error for '%s': %s", file_path, e)
                # Roll back partial state for this file so nothing half-indexed
                # remains in FAISS or the database.
                try:
                    self._remove_file_evidence(abs_path)
                except Exception:
                    pass

        # Final progress
        if self._progress_cb:
            self._progress_cb(IndexingProgress(
                current=total,
                total=total,
                current_file="",
                status="done",
            ))

        result = IndexingResult(
            total_files=total,
            indexed_files=indexed,
            skipped_files=skipped,
            total_chunks=total_chunks,
            errors=errors,
            unchanged_skipped=unchanged_skipped,
            no_content_skipped=no_content_skipped,
        )

        logger.info(
            "AI Indexing complete: %d/%d files indexed, %d chunks, %d errors",
            indexed, total, total_chunks, len(errors)
        )
        return result

    # ------------------------------------------------------------------ #
    # Per-file indexing
    # ------------------------------------------------------------------ #
    def _index_file(self, file_path: str) -> int:
        """Index a single file into the retrieval engine.

        Args:
            file_path: Path to the file.

        Returns:
            Number of chunks indexed (0 if skipped/failed).
        """
        from engines.config import detect_modality_and_ext
        modality, ext = detect_modality_and_ext(file_path)

        if modality == "image":
            return self._index_image(file_path)
        elif modality == "media":
            return self._index_media(file_path)
        else:
            # Documents and any remaining supported text
            return self._index_document(file_path)

    def _get_user_metadata_chunk(self, file_path: str, file_hash: str) -> Optional[EvidenceChunk]:
        if not self._db_store or not hasattr(self._db_store, "_session_factory"):
            return None
        try:
            import json
            from services.metadata_editor_service import build_user_metadata_chunk
            from services.sqlite_indexer import IndexedFile
            with self._db_store._session_factory() as session:
                row = session.query(IndexedFile).filter_by(
                    absolute_path=os.path.abspath(file_path)
                ).first()
                if row and row.user_metadata_json:
                    data = json.loads(row.user_metadata_json)
                    return build_user_metadata_chunk(
                        file_path, data, file_hash=file_hash or row.checksum or ""
                    )
        except Exception as exc:
            logger.debug("Failed to get user metadata chunk in indexer: %s", exc)
        return None

    def _index_document(self, file_path: str) -> int:
        """Index a text-based document."""
        file_hash = self._hash_file(file_path)
        chunks = self._evidence_engine.build_evidence(file_path) or []
        user_meta_chunk = self._get_user_metadata_chunk(file_path, file_hash)
        if user_meta_chunk:
            chunks.append(user_meta_chunk)
        if not chunks:
            return 0
        for c in chunks:
            c.file_hash = file_hash
        count, indexed_chunks = self._retrieval.index_chunks_detailed(chunks)
        self._persist_indexed(indexed_chunks, file_hash=file_hash)
        self._extract_graph(file_path, indexed_chunks)
        return count


    def _extract_graph(self, file_path: str, indexed_chunks: List[EvidenceChunk]) -> None:
        """Graph extraction is handled on-demand by FileGraphBuilder for instant performance."""
        return


    def _index_image(self, file_path: str) -> int:
        """Index an image using separate semantic chunks for filename, caption, and OCR.

        Creates focused, clean embeddings by splitting content into:
        1. Filename/metadata chunk — normalized name + keyword expansions
        2. AI caption chunk — clean vision model description (if available)
        3. OCR text chunk(s) — raw OCR text (only if not too noisy)
        """
        indexed = 0
        abs_path = os.path.abspath(file_path)
        file_name = os.path.basename(abs_path)
        file_hash = self._hash_file(file_path)
        indexed_chunks: List[EvidenceChunk] = []
        evidence_to_index: List[EvidenceChunk] = []

        # 1. Multi-layered extraction: OCR + Vision + Metadata
        ocr_texts = []
        caption_text = ""
        try:
            blocks = self._content_engine.extract(file_path)
            if blocks:
                for b in blocks:
                    if not b.text or not b.text.strip():
                        continue
                    lbl = (b.source_label or "").lower()
                    if "caption" in lbl:
                        caption_text = b.text.strip()
                    elif "ocr" in lbl:
                        ocr_texts.append(b.text.strip())
                    else:
                        # Other extracted text (metadata, etc.)
                        ocr_texts.append(b.text.strip())
        except Exception as e:
            logger.warning("Content extraction partial failure for %s: %s", file_path, e)

        # --- Chunk A: Filename / metadata chunk ---
        clean_name = file_name.replace('-', ' ').replace('_', ' ')
        name_text = f"Image: {file_name}\nNormalized name: {clean_name}"
        evidence_to_index.append(EvidenceChunk(
            chunk_id=uuid.uuid4().hex,
            text=name_text,
            file_path=abs_path,
            file_hash=file_hash,
            source_type="image_filename",
            source_index=0,
            source_label=f"Image: {file_name}",
            char_start=0,
            char_end=len(name_text),
            modality="image",
            confidence=0.9,
        ))

        # --- Chunk B: AI caption chunk (clean, semantic) ---
        if caption_text:
            evidence_to_index.append(EvidenceChunk(
                chunk_id=uuid.uuid4().hex,
                text=caption_text,
                file_path=abs_path,
                file_hash=file_hash,
                source_type="image_caption",
                source_index=1,
                source_label=f"Caption: {file_name}",
                char_start=0,
                char_end=len(caption_text),
                modality="image",
                confidence=0.95,
            ))

        # --- Chunk C: OCR text (only if not too noisy) ---
        for i, ocr in enumerate(ocr_texts):
            # Noise filter: skip OCR chunks where >60% of words are
            # very short (<=2 chars) or contain mostly non-alpha chars
            words = ocr.split()
            if words:
                noisy = sum(1 for w in words if len(w) <= 2 or not any(c.isalpha() for c in w))
                noise_ratio = noisy / len(words)
                if noise_ratio > 0.6:
                    logger.debug("Skipping noisy OCR chunk for %s (noise=%.0f%%)", file_name, noise_ratio * 100)
                    continue
            # Chunk long OCR into CHUNK_SIZE segments
            from engines.config import CHUNK_SIZE
            for start in range(0, len(ocr), CHUNK_SIZE):
                chunk_text = ocr[start:start + CHUNK_SIZE]
                if not chunk_text.strip():
                    continue
                evidence_to_index.append(EvidenceChunk(
                    chunk_id=uuid.uuid4().hex,
                    text=chunk_text,
                    file_path=abs_path,
                    file_hash=file_hash,
                    source_type="image_ocr",
                    source_index=2 + i,
                    source_label=f"OCR: {file_name}",
                    char_start=start,
                    char_end=start + len(chunk_text),
                    modality="image",
                    confidence=0.7,
                ))

        # --- Chunk D: User metadata (if edited by user) ---
        user_meta_chunk = self._get_user_metadata_chunk(abs_path, file_hash)
        if user_meta_chunk:
            evidence_to_index.append(user_meta_chunk)

        count, persisted = self._retrieval.index_chunks_detailed(evidence_to_index)
        indexed += count
        indexed_chunks.extend(persisted)

        # 2. CLIP embedding for visual search if available
        if self._clip_engine.is_available():
            try:
                if self._resources is not None:
                    with self._resources.vision():
                        clip_vector = self._clip_engine.embed_image(file_path)
                else:
                    clip_vector = self._clip_engine.embed_image(file_path)

                if clip_vector is not None:
                    chunk_id = uuid.uuid4().hex
                    clip_evidence = EvidenceChunk(
                        chunk_id=chunk_id,
                        text=f"[Visual Image Content: {file_name}]",
                        file_path=abs_path,
                        file_hash=file_hash,
                        source_type="clip_visual",
                        source_index=1,
                        source_label="Visual Content",
                        char_start=0,
                        char_end=0,
                        modality="image",
                    )
                    embedding_dim = self._retrieval._vector.dimension
                    if clip_vector.shape[0] != embedding_dim:
                        import numpy as np
                        padded = np.zeros(embedding_dim, dtype=np.float32)
                        padded[:clip_vector.shape[0]] = clip_vector
                        padded = padded / (np.linalg.norm(padded) + 1e-8)
                        clip_vector = padded
                    if self._retrieval._vector.add(chunk_id, clip_vector):
                        self._retrieval._evidence[chunk_id] = clip_evidence
                        indexed_chunks.append(clip_evidence)
                        indexed += 1
            except Exception as e:
                logger.debug("CLIP embedding error for %s: %s", file_path, e)

        self._persist_indexed(indexed_chunks, file_hash=file_hash)
        self._extract_graph(file_path, indexed_chunks)
        return indexed


    def _index_media(self, file_path: str) -> int:
        """Full media indexing: transcribes 100% of spoken audio/video content via Whisper and persists all transcript chunks into FAISS and SQLite."""
        abs_path = os.path.abspath(file_path)
        fname = os.path.basename(abs_path)
        ext = os.path.splitext(fname)[1].lower()

        try:
            file_hash = self._content_engine._hash_file(abs_path)
        except Exception:
            file_hash = ""

        modality = "video" if ext in _VIDEO_EXT else "audio"
        evidence_chunks: List[EvidenceChunk] = []

        # 1. Extract full Whisper transcripts and metadata blocks
        try:
            blocks = self._content_engine.extract(file_path)
            if blocks:
                for idx, b in enumerate(blocks):
                    if b.text and b.text.strip():
                        chunk_text = f"[{modality.capitalize()} {fname} ({b.source_label})]:\n{b.text.strip()}"
                        evidence_chunks.append(EvidenceChunk(
                            chunk_id=uuid.uuid4().hex,
                            text=chunk_text,
                            file_path=abs_path,
                            file_hash=file_hash,
                            source_type=b.source_type or "transcript",
                            source_index=idx,
                            source_label=f"{fname} ({b.source_label})",
                            char_start=0,
                            char_end=len(chunk_text),
                            modality=modality,
                            timestamp_start=b.timestamp_start,
                            timestamp_end=b.timestamp_end,
                            confidence=0.9,
                        ))
        except Exception as e:
            logger.warning("Audio/Video transcript extraction partial failure for %s: %s", file_path, e)

        # 2. Always include a fallback metadata chunk so file is indexed even if transcript is empty
        if not evidence_chunks:
            evidence_chunks.append(EvidenceChunk(
                chunk_id=uuid.uuid4().hex,
                text=f"[{modality.capitalize()} file: {fname}]",
                file_path=abs_path,
                file_hash=file_hash,
                source_type="media_file",
                source_index=0,
                source_label="Media Metadata",
                char_start=0,
                char_end=0,
                modality=modality,
            ))

        # 3. User metadata (if edited by user)
        user_meta_chunk = self._get_user_metadata_chunk(abs_path, file_hash)
        if user_meta_chunk:
            evidence_chunks.append(user_meta_chunk)

        count, indexed_chunks = self._retrieval.index_chunks_detailed(evidence_chunks)
        self._persist_indexed(indexed_chunks, file_hash=file_hash)
        self._extract_graph(file_path, indexed_chunks)
        return count



    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #
    def _persist_indexed(
        self, indexed_chunks: List[EvidenceChunk], file_hash: str = None
    ) -> None:
        if not indexed_chunks or self._db_store is None:
            return
        try:
            self._db_store.store_evidence(indexed_chunks)
            first = indexed_chunks[0]
            chunk_ids = [c.chunk_id for c in indexed_chunks]
            self._db_store.store_vector_maps(
                chunk_ids, first.file_path, first.file_hash or file_hash or "",
                EMBEDDING_MODEL,
            )
        except Exception as e:
            logger.error("Failed to persist indexed chunks: %s", e)
            raise

    def _remove_file_evidence(self, file_path: str) -> None:
        """Remove all evidence/vectors for a file from FAISS + DB + graph."""
        try:
            self._retrieval.remove_file(file_path)
        except Exception as e:
            logger.error("Failed to remove vectors for %s: %s", file_path, e)
        if self._db_store is not None:
            try:
                self._db_store.delete_evidence_by_file(file_path)
            except Exception as e:
                logger.error("Failed to remove DB evidence for %s: %s", file_path, e)
        if self._graph is not None:
            try:
                self._graph.remove_file(file_path)
            except Exception as e:
                logger.error("Failed to remove graph data for %s: %s", file_path, e)

    def reindex_file(self, file_path: str, cancel_event=None) -> int:
        """Re-index a single file (remove stale evidence first, then index)."""
        abs_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_path):
            return 0
        self._remove_file_evidence(abs_path)
        if cancel_event and cancel_event.is_set():
            return 0
        return self._index_file(abs_path)

    @staticmethod
    def _hash_file(file_path: str) -> str:
        """Compute fast, reliable hash of a file for indexing skip checks."""
        try:
            size = os.path.getsize(file_path)
            mtime = os.path.getmtime(file_path)
            if size < 2000000:
                from services.file_identity import calculate_sha256
                return calculate_sha256(file_path)
            else:
                # Fast fingerprint for large media/binary files
                import hashlib
                hasher = hashlib.sha256()
                hasher.update(f"{size}_{mtime}".encode("utf-8"))
                with open(file_path, "rb") as f:
                    hasher.update(f.read(65536))
                return hasher.hexdigest()
        except Exception:
            return ""


    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    def _discover_files(self, folder_path: str, recursive: bool) -> List[str]:
        """Discover all indexable files in a folder sorted by requested priority.

        Sequence:
        1. Images (Rank 1)
        2. Documents & Text files (Rank 2)
        3. Audio (Rank 3)
        4. Video (Rank 4)
        5. Others (Rank 5)
        """
        files: List[str] = []

        if recursive:
            for root, dirs, filenames in os.walk(folder_path):
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith('.') and d not in (
                        'node_modules', '__pycache__', 'venv', '.git',
                        'build', 'dist', '.cache', 'cache',
                    )
                ]
                for fname in filenames:
                    if fname.startswith('.'):
                        continue
                    fpath = os.path.join(root, fname)
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in _SKIP_EXT:
                        continue
                    files.append(fpath)
        else:
            for fname in os.listdir(folder_path):
                if fname.startswith('.'):
                    continue
                fpath = os.path.join(folder_path, fname)
                if not os.path.isfile(fpath):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext in _SKIP_EXT:
                    continue
                files.append(fpath)

        def _indexing_priority(fpath: str) -> int:
            ext = os.path.splitext(fpath)[1].lower()
            if ext in _IMAGE_EXT:
                return 1
            elif ext in _TEXT_EXTRACTABLE or ext in (
                '.txt', '.md', '.markdown', '.pdf', '.docx', '.pptx', '.xlsx',
                '.csv', '.py', '.json', '.yaml', '.yml', '.xml', '.log', '.ini', '.toml'
            ):
                return 2
            elif ext in _AUDIO_EXT:
                return 3
            elif ext in _VIDEO_EXT:
                return 4
            return 5

        return sorted(files, key=lambda f: (_indexing_priority(f), f))

