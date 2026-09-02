"""CSV file extractor using the csv standard library."""

import csv
import logging

from .base_extractor import BaseExtractor

logger = logging.getLogger(__name__)


class CsvExtractor(BaseExtractor):
    """Extractor for CSV files.

    Uses csv.reader to read all rows and join them as text.
    """

    def extract(self, file_path: str) -> str:
        """Extract text from a CSV file.

        Args:
            file_path: Path to the CSV file.

        Returns:
            Extracted text content as a string. Returns empty string on failure.
        """
        logger.info("Starting CSV extraction: %s", file_path)
        try:
            if not self.validate_file(file_path):
                return ""

            text_parts: list[str] = []

            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                for row in reader:
                    row_text = "\t".join(row)
                    if row_text.strip():
                        text_parts.append(row_text)

            result = "\n".join(text_parts)
            logger.info("Finished CSV extraction: %s", file_path)
            return result

        except Exception as e:
            logger.error("Error extracting CSV from %s: %s", file_path, str(e))
            return ""
