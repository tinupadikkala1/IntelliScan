"""Content Merger for combining OCR and vision results into ContentBlocks."""

from __future__ import annotations

import logging
from typing import List, Optional

from engines.content_engine import ContentBlock
from .ocr_engine import OCRResult
from .vision_engine import VisionResult

logger = logging.getLogger(__name__)


class ContentMerger:
    """Merges OCR text and vision captions into unified ContentBlocks.

    Combines output from OCREngine and VisionEngine into a coherent
    set of ContentBlocks for a single image file.
    """

    def merge(
        self,
        file_path: str,
        ocr_result: Optional[OCRResult] = None,
        vision_result: Optional[VisionResult] = None,
    ) -> List[ContentBlock]:
        """Merge OCR and vision results into ContentBlocks.

        Args:
            file_path: Source image file path.
            ocr_result: OCR extraction result (if available).
            vision_result: Vision captioning result (if available).

        Returns:
            List of ContentBlock objects.
        """
        blocks: List[ContentBlock] = []

        if ocr_result and ocr_result.text.strip():
            blocks.append(ContentBlock(
                text=ocr_result.text,
                source_type="ocr",
                source_index=0,
                source_label="OCR Text",
                file_path=file_path,
                modality="image",
                confidence=ocr_result.confidence,
            ))

        if vision_result and vision_result.caption.strip():
            blocks.append(ContentBlock(
                text=vision_result.caption,
                source_type="caption",
                source_index=len(blocks),
                source_label="Image Caption",
                file_path=file_path,
                modality="image",
                confidence=vision_result.confidence,
            ))

        return blocks
