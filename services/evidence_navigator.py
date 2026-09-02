"""Evidence navigator — maps a retrieval result to an exact source location.

The retrieval engine returns evidence; the UI navigation layer interprets it.
This module keeps modality-specific navigation (PDF page jump, audio/video
seek, image preview) out of the retrieval engines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EvidenceLocation:
    """Generic navigation target derived from a retrieval result.

    Attributes:
        file_path: Absolute path of the source file.
        modality: 'document', 'image', 'audio' or 'video'.
        source_type: Evidence source type (page, slide, ocr, transcript...).
        source_index: Zero-based source index (page/slide index).
        source_label: Human-readable label (e.g. 'Page 3', '02:14 - 02:31').
        timestamp_start: Start time in seconds (audio/video).
        timestamp_end: End time in seconds (audio/video).
        page: 1-based page number for PDF navigation (derived from source).
        score: Retrieval similarity score (optional).
        metadata: Extra metadata dict.
    """

    file_path: str
    modality: str = "document"
    source_type: str = ""
    source_index: int = 0
    source_label: str = ""
    timestamp_start: float = 0.0
    timestamp_end: float = 0.0
    page: int = 0
    score: float = 0.0
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_result(cls, result) -> "EvidenceLocation":
        """Build an EvidenceLocation from a RetrievalResult-like object."""
        page = 0
        if result.source_type == "page" and result.source_index is not None:
            page = result.source_index + 1
        return cls(
            file_path=result.file_path,
            modality=getattr(result, "modality", "document"),
            source_type=result.source_type or "",
            source_index=result.source_index or 0,
            source_label=result.source_label or "",
            timestamp_start=getattr(result, "timestamp_start", 0.0) or 0.0,
            timestamp_end=getattr(result, "timestamp_end", 0.0) or 0.0,
            page=page,
            score=getattr(result, "score", 0.0) or 0.0,
            metadata=getattr(result, "metadata", None) or {},
        )

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "modality": self.modality,
            "source_type": self.source_type,
            "source_index": self.source_index,
            "source_label": self.source_label,
            "timestamp_start": self.timestamp_start,
            "timestamp_end": self.timestamp_end,
            "page": self.page,
            "score": self.score,
            "metadata": self.metadata,
        }


class EvidenceNavigator:
    """Opens an evidence location in the appropriate viewer.

    The MainWindow provides callbacks rather than hard dependencies so this
    service stays decoupled from Qt widgets:
        open_file(path)          — open/activate a file
        jump_pdf(path, page)     — open a PDF at a specific page
        jump_slide(path, idx)    — open a PPTX at a specific slide
        jump_section(path, idx)  — open a DOCX at a specific section
        play_media(path, seconds) — open audio/video and seek to a time
        preview_file(path)       — show a file in the preview panel
    """

    def __init__(
        self,
        open_file=None,
        jump_pdf=None,
        jump_slide=None,
        jump_section=None,
        play_media=None,
        preview_file=None,
    ):
        self._open_file = open_file
        self._jump_pdf = jump_pdf
        self._jump_slide = jump_slide
        self._jump_section = jump_section
        self._play_media = play_media
        self._preview_file = preview_file

    def navigate(self, location: EvidenceLocation) -> None:
        """Dispatch an evidence location to the correct viewer."""
        if not location.file_path:
            logger.warning("Evidence navigation: no file path")
            return

        modality = (location.modality or "").lower()
        source_type = (location.source_type or "").lower()

        # Documents: PDF page jump when page info is available
        if modality == "document" and location.page and self._jump_pdf:
            self._jump_pdf(location.file_path, location.page)
            return

        # PPTX slide navigation (Batch 4 M0-05)
        if source_type == "slide" and self._jump_slide:
            self._jump_slide(location.file_path, location.source_index)
            return

        # DOCX / section-based navigation (Batch 4 M0-05)
        if source_type == "section" and self._jump_section:
            self._jump_section(location.file_path, location.source_index)
            return

        # Audio / video: seek to timestamp
        if modality in ("audio", "video") and self._play_media:
            self._play_media(location.file_path, location.timestamp_start)
            return

        # Images: preview in place
        if modality == "image" and self._preview_file:
            self._preview_file(location.file_path)
            return

        # Default: just open the file
        if self._open_file:
            self._open_file(location.file_path)
            return

        logger.info("No navigator callback for %s evidence", modality)
