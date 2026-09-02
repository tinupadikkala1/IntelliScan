"""Factory that dispatches to the correct multimodal extractor."""

from __future__ import annotations

import os
import logging
from typing import List, Optional

from engines.content_engine import ContentBlock
from .base_extractor import BaseMultimodalExtractor

logger = logging.getLogger(__name__)


class MultimodalExtractorFactory:
    """Routes files to the appropriate modality-specific extractor.

    Checks file extension and delegates to Document, Image, Audio,
    or Video extractor as appropriate.
    """

    def __init__(self) -> None:
        from .document_extractor import DocumentExtractor
        from .image_extractor import ImageExtractor
        from .audio_extractor import AudioExtractor
        from .video_extractor import VideoExtractor

        self._extractors: List[BaseMultimodalExtractor] = [
            ImageExtractor(),
            AudioExtractor(),
            VideoExtractor(),
            DocumentExtractor(),  # Last — widest extension set
        ]

    def get_extractor(self, file_path: str) -> Optional[BaseMultimodalExtractor]:
        """Find the appropriate extractor for a file.

        Args:
            file_path: Path to the file.

        Returns:
            The matching extractor, or None if unsupported.
        """
        for extractor in self._extractors:
            if extractor.can_handle(file_path):
                return extractor
        return None

    def extract(self, file_path: str) -> List[ContentBlock]:
        """Extract content blocks from a file using the appropriate extractor.

        Args:
            file_path: Path to the file.

        Returns:
            List of ContentBlock objects. Empty list if unsupported or error.
        """
        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            logger.error("File not found: %s", file_path)
            return []

        extractor = self.get_extractor(file_path)
        if extractor is None:
            logger.warning("No extractor for: %s", file_path)
            return []

        try:
            blocks = extractor.extract(file_path)
            logger.info(
                "Extracted %d blocks from '%s' via %s",
                len(blocks), file_path, type(extractor).__name__
            )
            return blocks
        except Exception as e:
            logger.error("Extraction failed for '%s': %s", file_path, e)
            return []

    def is_supported(self, file_path: str) -> bool:
        """Check if a file type is supported.

        Args:
            file_path: Path to check.

        Returns:
            True if any extractor can handle it.
        """
        return self.get_extractor(file_path) is not None

    def supported_extensions(self) -> set:
        """Return all supported extensions across all extractors."""
        all_ext = set()
        for extractor in self._extractors:
            all_ext.update(extractor.supported_extensions())
        return all_ext
