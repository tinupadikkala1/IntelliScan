"""OCR Engine for extracting text and digits from images.

Uses EasyOCR (deep learning scene text detection and recognition for Hindi + English)
with automatic fallback to Tesseract for maximum accuracy and resilience.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Global singleton for EasyOCR Reader to avoid reloading models on every image
_EASYOCR_READER = None
_EASYOCR_LOCK = threading.Lock()


def get_easyocr_reader(languages: Tuple[str, ...] = ("hi", "en")):
    """Get or lazily initialize the shared EasyOCR reader instance."""
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        with _EASYOCR_LOCK:
            if _EASYOCR_READER is None:
                try:
                    import easyocr
                    logger.info("Initializing EasyOCR reader with languages: %s (CPU)", languages)
                    _EASYOCR_READER = easyocr.Reader(list(languages), gpu=False, verbose=False)
                except Exception as e:
                    logger.warning("Failed to initialize EasyOCR: %s", e)
                    return None
    return _EASYOCR_READER


@dataclass
class OCRResult:
    """Result from OCR extraction."""
    text: str
    confidence: float
    language: str


class OCREngine:
    """Extracts text and digits from images using EasyOCR (with Tesseract fallback).

    Capable of reading English, Hindi (Devanagari), and digits accurately
    from natural scene images, road signs, screenshots, and scanned documents.
    """

    def __init__(self, language: str = "hin+eng", use_easyocr: bool = True) -> None:
        """Initialize OCR engine.

        Args:
            language: Language code (default: 'hin+eng' for bilingual Hindi + English).
            use_easyocr: Whether to use EasyOCR as primary engine (default: True).
        """
        self._language = language
        self._use_easyocr = use_easyocr

    def extract_text(self, image_path: str) -> Optional[OCRResult]:
        """Extract text and numbers from an image file.

        Args:
            image_path: Path to the image file.

        Returns:
            OCRResult with extracted text, confidence, and language, or None on failure.
        """
        if not os.path.isfile(image_path):
            logger.error("OCR: file not found: %s", image_path)
            return None

        # 1. Try EasyOCR first
        if self._use_easyocr:
            easy_res = self._extract_with_easyocr(image_path)
            if easy_res and easy_res.text.strip():
                return easy_res

        # 2. Fallback to Tesseract
        return self._extract_with_tesseract(image_path)

    def extract_from_array(self, image_array) -> Optional[OCRResult]:
        """Extract text from a numpy array (OpenCV / PIL image).

        Args:
            image_array: numpy ndarray (RGB, BGR, or grayscale).

        Returns:
            OCRResult or None.
        """
        if image_array is None:
            return None

        # 1. Try EasyOCR first
        if self._use_easyocr:
            easy_res = self._extract_with_easyocr(image_array)
            if easy_res and easy_res.text.strip():
                return easy_res

        # 2. Fallback to Tesseract
        return self._extract_with_tesseract_array(image_array)

    def _extract_with_easyocr(self, image_input: Union[str, any]) -> Optional[OCRResult]:
        """Extract text using EasyOCR."""
        try:
            reader = get_easyocr_reader()
            if reader is None:
                return None

            results = reader.readtext(image_input)
            if not results:
                return None

            # Sort detected bounding boxes in natural reading order (top-to-bottom, left-to-right)
            def _sort_key(item):
                bbox = item[0]
                # Vertical center rounded to line bins
                y_center = (bbox[0][1] + bbox[2][1]) / 2.0
                x_min = bbox[0][0]
                return (round(y_center / 28.0) * 28.0, x_min)

            sorted_results = sorted(results, key=_sort_key)

            lines = []
            confidences = []
            for bbox, text, conf in sorted_results:
                text_clean = text.strip()
                if conf >= 0.20 and text_clean:
                    lines.append(text_clean)
                    confidences.append(float(conf))

            if not lines:
                return None

            avg_conf = sum(confidences) / len(confidences) if confidences else 0.5
            return OCRResult(
                text="\n".join(lines),
                confidence=avg_conf,
                language="hi+en",
            )

        except Exception as exc:
            logger.debug("EasyOCR extraction error: %s; falling back", exc)
            return None

    def _extract_with_tesseract(self, image_path: str) -> Optional[OCRResult]:
        """Fallback extraction using Tesseract."""
        try:
            import cv2
            import pytesseract

            img = cv2.imread(image_path)
            if img is None:
                from PIL import Image
                pil_img = Image.open(image_path)
                return self._extract_with_tesseract_array(pil_img)

            return self._extract_with_tesseract_array(img)

        except Exception as exc:
            logger.debug("Tesseract fallback failed: %s", exc)
            return None

    def _extract_with_tesseract_array(self, image_input) -> Optional[OCRResult]:
        """Run Tesseract on an array or PIL image."""
        try:
            import pytesseract

            # Configure tessdata path if project data/tessdata exists
            config = ""
            project_tessdata = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "data", "tessdata")
            )
            lang = self._language
            if os.path.isdir(project_tessdata):
                config = f"--tessdata-dir {project_tessdata}"
                lang = "hin+eng"

            text = pytesseract.image_to_string(image_input, lang=lang, config=config)
            if text and text.strip():
                return OCRResult(
                    text=text.strip(),
                    confidence=0.7,
                    language=lang,
                )
        except Exception as exc:
            logger.debug("Tesseract image_to_string failed: %s", exc)

        return None

    def is_available(self) -> bool:
        """Check if any OCR engine is available.

        Returns:
            True if EasyOCR or Tesseract is available.
        """
        try:
            import easyocr
            return True
        except ImportError:
            pass

        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False
