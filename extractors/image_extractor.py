"""Image extractor — OCR + vision captioning for images."""

from __future__ import annotations

import logging
import os
from typing import List

from engines.content_engine import ContentBlock
from engines.config import IMAGE_EXTENSIONS, OLLAMA_BASE_URL, VISION_MODEL
from .base_extractor import BaseMultimodalExtractor

logger = logging.getLogger(__name__)

_IMAGE_EXT = IMAGE_EXTENSIONS


def ocr_image_bytes(data: bytes) -> str:
    """Run Tesseract OCR on raw image bytes (shared by ImageExtractor and
    embedded-document-image extraction). Returns extracted text or ""."""
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        import pytesseract
        text = pytesseract.image_to_string(img)
        return text.strip() if text else ""
    except ImportError:
        logger.debug("pytesseract not available, skipping OCR")
        return ""
    except Exception as e:
        logger.debug("OCR failed: %s", e)
        return ""


def caption_image_bytes(data: bytes) -> str:
    """Generate a caption for raw image bytes using the configured vision
    model via Ollama (shared by ImageExtractor and embedded-image
    extraction). Returns caption text or ""."""
    try:
        import base64
        import requests

        image_b64 = base64.b64encode(data).decode("utf-8")
        url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
        response = requests.post(
            url,
            json={
                "model": VISION_MODEL,
                "prompt": "Describe this image in detail. Include any text, objects, people, scenes, colors, and layout you can see.",
                "images": [image_b64],
                "stream": False,
            },
            timeout=60,
        )

        if response.status_code == 200:
            caption = response.json().get("response", "").strip()
            if caption:
                return caption
        return ""
    except Exception as e:
        logger.debug("Vision captioning unavailable: %s", e)
        return ""


class ImageExtractor(BaseMultimodalExtractor):
    """Extracts text content from images using OCR and vision captioning.

    Uses:
    - OpenCV + pytesseract/easyocr for OCR text extraction
    - Ollama vision model for image captioning (if available)
    """

    def supported_extensions(self) -> set:
        return _IMAGE_EXT

    def extract(self, file_path: str) -> List[ContentBlock]:
        """Extract content from an image file.

        Combines OCR text extraction with vision-based captioning.

        Args:
            file_path: Path to the image file.

        Returns:
            List of ContentBlock objects with OCR text and/or captions.
        """
        file_path = os.path.abspath(file_path)
        blocks: List[ContentBlock] = []

        # Try OCR extraction
        ocr_text = self._extract_ocr(file_path)
        if ocr_text and ocr_text.strip():
            blocks.append(ContentBlock(
                text=ocr_text,
                source_type="ocr",
                source_index=0,
                source_label="OCR Text",
                file_path=file_path,
                modality="image",
                confidence=0.8,
            ))

        # Try vision captioning
        caption = self._extract_caption(file_path)
        if caption and caption.strip():
            blocks.append(ContentBlock(
                text=caption,
                source_type="caption",
                source_index=1,
                source_label="Image Caption",
                file_path=file_path,
                modality="image",
                confidence=0.7,
            ))

        if not blocks:
            # Fallback: at minimum, record the filename as content
            basename = os.path.basename(file_path)
            blocks.append(ContentBlock(
                text=f"Image file: {basename}",
                source_type="filename",
                source_index=0,
                source_label="Filename",
                file_path=file_path,
                modality="image",
                confidence=0.3,
            ))

        return blocks

    def _extract_ocr(self, file_path: str) -> str:
        """Extract text from image using Tesseract OCR.

        Args:
            file_path: Path to the image.

        Returns:
            Extracted text string, or empty string on failure.
        """
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            return ocr_image_bytes(data)
        except Exception as e:
            logger.debug("OCR failed: %s", e)
            return ""

    def _extract_caption(self, file_path: str) -> str:
        """Generate image caption using the configured vision model.

        Args:
            file_path: Path to the image.

        Returns:
            Caption text, or empty string if vision model unavailable.
        """
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            return caption_image_bytes(data)
        except Exception as e:
            logger.debug("Vision captioning unavailable: %s", e)
            return ""
