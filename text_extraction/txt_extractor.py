"""Text file extractor with automatic encoding detection."""

import logging

import chardet

from .base_extractor import BaseExtractor

logger = logging.getLogger(__name__)


class TxtExtractor(BaseExtractor):
    """Extractor for plain text files.

    Uses chardet for automatic encoding detection with fallback to
    UTF-8 with error replacement.
    """

    def extract(self, file_path: str) -> str:
        """Extract text from a plain text file.

        Args:
            file_path: Path to the text file.

        Returns:
            File content as a string. Returns empty string on failure.
        """
        logger.info("Starting text extraction: %s", file_path)
        try:
            if not self.validate_file(file_path):
                return ""

            with open(file_path, "rb") as f:
                raw_data = f.read()

            if not raw_data:
                logger.info("File is empty: %s", file_path)
                return ""

            detected = chardet.detect(raw_data)
            encoding = detected.get("encoding") or "utf-8"
            logger.debug(
                "Detected encoding '%s' with confidence %.2f for: %s",
                encoding,
                detected.get("confidence", 0.0),
                file_path,
            )

            try:
                text = raw_data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                logger.warning(
                    "Failed to decode with '%s', falling back to utf-8: %s",
                    encoding,
                    file_path,
                )
                text = raw_data.decode("utf-8", errors="replace")

            logger.info("Finished text extraction: %s", file_path)
            return text

        except Exception as e:
            logger.error("Error extracting text from %s: %s", file_path, str(e))
            return ""
