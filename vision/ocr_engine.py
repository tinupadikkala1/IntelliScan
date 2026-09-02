"""OCR Engine for extracting text from images.

Uses pytesseract (Tesseract) with OpenCV preprocessing for
reliable text extraction from images, screenshots, and scanned documents.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """Result from OCR extraction."""
    text: str
    confidence: float
    language: str


class OCREngine:
    """Extracts text from images using OCR (Tesseract via pytesseract).

    Applies preprocessing (grayscale, thresholding, denoising) to improve
    OCR accuracy on various image types.
    """

    def __init__(self, language: str = "eng") -> None:
        """Initialize OCR engine.

        Args:
            language: Tesseract language code (default: English).
        """
        self._language = language

    def extract_text(self, image_path: str) -> Optional[OCRResult]:
        """Extract text from an image file.

        Args:
            image_path: Path to the image file.

        Returns:
            OCRResult with extracted text, or None on failure.
        """
        if not os.path.isfile(image_path):
            logger.error("OCR: file not found: %s", image_path)
            return None

        try:
            import cv2
            import numpy as np

            img = cv2.imread(image_path)
            if img is None:
                logger.error("OCR: cannot read image: %s", image_path)
                return None

            # Preprocessing pipeline
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # Denoise
            denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)

            # Adaptive threshold for mixed lighting
            thresh = cv2.adaptiveThreshold(
                denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )

            # Try pytesseract
            try:
                import pytesseract

                # Get detailed data with confidence
                data = pytesseract.image_to_data(
                    thresh, lang=self._language, output_type=pytesseract.Output.DICT
                )

                # Calculate average confidence
                confidences = [
                    int(c) for c in data['conf'] if int(c) > 0
                ]
                avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

                # Extract text
                text = pytesseract.image_to_string(thresh, lang=self._language)
                if not text.strip():
                    # Try without preprocessing
                    text = pytesseract.image_to_string(img, lang=self._language)

                if text.strip():
                    return OCRResult(
                        text=text.strip(),
                        confidence=avg_conf / 100.0,
                        language=self._language,
                    )

            except ImportError:
                logger.warning("pytesseract not installed — OCR unavailable")
                return None

        except ImportError:
            logger.warning("OpenCV not available for OCR preprocessing")
            return None
        except Exception as e:
            logger.error("OCR extraction error: %s", e)
            return None

        return None

    def extract_from_array(self, image_array) -> Optional[OCRResult]:
        """Extract text from a numpy array (OpenCV image).

        Args:
            image_array: numpy ndarray (BGR or grayscale).

        Returns:
            OCRResult or None.
        """
        try:
            import pytesseract
            import cv2

            if len(image_array.shape) == 3:
                gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
            else:
                gray = image_array

            text = pytesseract.image_to_string(gray, lang=self._language)
            if text.strip():
                return OCRResult(
                    text=text.strip(),
                    confidence=0.7,
                    language=self._language,
                )
        except ImportError:
            pass
        except Exception as e:
            logger.error("OCR from array failed: %s", e)

        return None

    def is_available(self) -> bool:
        """Check if OCR engine is available.

        Returns:
            True if pytesseract and tesseract are installed.
        """
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False
