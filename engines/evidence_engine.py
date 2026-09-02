"""Evidence engine for building searchable evidence chunks from documents.

Takes structured ContentBlocks from UniversalContentEngine and splits them
into overlapping evidence chunks suitable for embedding and semantic search.
Each chunk retains full provenance information for citation purposes.
"""

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass

from .config import CHUNK_OVERLAP, CHUNK_SIZE
from .content_engine import ContentBlock, UniversalContentEngine

logger = logging.getLogger(__name__)


@dataclass
class EvidenceChunk:
    """An evidence chunk with full provenance for citation.

    Attributes:
        chunk_id: Unique identifier (uuid4 hex) for this chunk.
        text: The chunk text content.
        file_path: Absolute path to the source file.
        file_hash: SHA-256 hash of the source file.
        source_type: Type of source (page, slide, sheet, file, section).
        source_index: Zero-based index of the source within the document.
        source_label: Human-readable label (e.g., 'Page 3', 'Slide 5').
        char_start: Start character offset within the ContentBlock.
        char_end: End character offset within the ContentBlock.
        modality: Content modality ('document', 'image', 'audio', 'video').
        timestamp_start: Start timestamp in seconds (audio/video).
        timestamp_end: End timestamp in seconds (audio/video).
        confidence: Extraction confidence (0.0 - 1.0).
        metadata: Additional metadata dict.
    """

    chunk_id: str
    text: str
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


class EvidenceEngine:
    """Builds evidence chunks from documents for embedding and retrieval.

    Uses UniversalContentEngine to extract structured content, then splits
    each ContentBlock into overlapping chunks of configurable size.
    """

    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
    ) -> None:
        """Initialize EvidenceEngine.

        Args:
            chunk_size: Target character count per evidence chunk.
            chunk_overlap: Number of overlapping characters between chunks.
        """
        self._content_engine = UniversalContentEngine()
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def build_evidence(self, file_path: str) -> list[EvidenceChunk]:
        """Build evidence chunks from a file.

        Extracts structured content blocks, computes the file hash, then
        splits each block into overlapping chunks with provenance metadata.

        Args:
            file_path: Path to the file to process.

        Returns:
            List of EvidenceChunk objects. Returns empty list on error.
        """
        file_path = os.path.abspath(file_path)
        logger.info("EvidenceEngine: building evidence for '%s'", file_path)

        try:
            # Extract content blocks
            content_blocks = self._content_engine.extract(file_path)
            if not content_blocks:
                logger.warning(
                    "EvidenceEngine: no content blocks from '%s'", file_path
                )
                return []

            # Retrieve file hash from content blocks metadata if available, otherwise compute it
            file_hash = None
            if content_blocks:
                first_block = content_blocks[0]
                if getattr(first_block, 'metadata', None) and "file_hash" in first_block.metadata:
                    file_hash = first_block.metadata["file_hash"]
            
            if not file_hash:
                file_hash = self._compute_hash(file_path)

            # Build evidence chunks from content blocks
            evidence_chunks: list[EvidenceChunk] = []
            for block in content_blocks:
                chunks = self._split_block(block, file_hash)
                evidence_chunks.extend(chunks)

            logger.info(
                "EvidenceEngine: produced %d evidence chunks from '%s'",
                len(evidence_chunks), file_path
            )
            return evidence_chunks

        except Exception as exc:
            logger.error(
                "EvidenceEngine: unexpected error processing '%s': %s",
                file_path, exc, exc_info=True
            )
            return []

    def _split_block(
        self, block: ContentBlock, file_hash: str
    ) -> list[EvidenceChunk]:
        """Split a ContentBlock into overlapping evidence chunks.

        Args:
            block: The ContentBlock to split.
            file_hash: SHA-256 hash of the source file.

        Returns:
            List of EvidenceChunk objects derived from this block.
        """
        text = block.text
        text_len = len(text)
        chunks: list[EvidenceChunk] = []

        if text_len == 0:
            return chunks

        # If the block is small enough, emit a single chunk
        if text_len <= self._chunk_size:
            chunks.append(self._build_chunk(
                text=text,
                file_hash=file_hash,
                block=block,
                char_start=0,
                char_end=text_len,
            ))
            return chunks

        # Split with overlap
        start = 0
        while start < text_len:
            end = min(start + self._chunk_size, text_len)

            # Try to break at word boundary if not at end of text
            if end < text_len:
                # Look back for a space in the last 20% of the chunk
                search_start = end - self._chunk_size // 5
                space_pos = text.rfind(' ', search_start, end)
                if space_pos > start:
                    end = space_pos + 1

            chunk_text = text[start:end]
            if chunk_text.strip():
                chunks.append(self._build_chunk(
                    text=chunk_text,
                    file_hash=file_hash,
                    block=block,
                    char_start=start,
                    char_end=end,
                ))

            # Advance by chunk_size - overlap
            step = self._chunk_size - self._chunk_overlap
            if step <= 0:
                step = self._chunk_size  # Safety: prevent infinite loop
            start += step

            # Avoid creating a tiny trailing chunk
            if start < text_len and (text_len - start) < self._chunk_overlap:
                # Extend previous chunk to end if remaining is very small
                break

        return chunks

    def _build_chunk(
        self, text: str, file_hash: str, block: ContentBlock,
        char_start: int, char_end: int,
    ) -> EvidenceChunk:
        """Build an EvidenceChunk from a ContentBlock, carrying modality
        and timestamp provenance through to the evidence layer."""
        return EvidenceChunk(
            chunk_id=uuid.uuid4().hex,
            text=text,
            file_path=block.file_path,
            file_hash=file_hash,
            source_type=block.source_type,
            source_index=block.source_index,
            source_label=block.source_label,
            char_start=char_start,
            char_end=char_end,
            modality=getattr(block, "modality", "document"),
            timestamp_start=getattr(block, "timestamp_start", 0.0) or 0.0,
            timestamp_end=getattr(block, "timestamp_end", 0.0) or 0.0,
            confidence=getattr(block, "confidence", 1.0) or 1.0,
            metadata=getattr(block, "metadata", None),
        )

    @staticmethod
    def _compute_hash(file_path: str) -> str:
        """Compute SHA-256 hash of a file.

        Args:
            file_path: Path to the file.

        Returns:
            Hex digest of the SHA-256 hash.
        """
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
