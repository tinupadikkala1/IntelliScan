"""JSON file extractor using the json standard library."""

import json
import logging

from .base_extractor import BaseExtractor

logger = logging.getLogger(__name__)


class JsonExtractor(BaseExtractor):
    """Extractor for JSON files.

    Pretty-prints the JSON content as readable text.
    """

    def extract(self, file_path: str) -> str:
        """Extract text from a JSON file.

        Args:
            file_path: Path to the JSON file.

        Returns:
            Pretty-printed JSON content as a string. Returns empty string on failure.
        """
        logger.info("Starting JSON extraction: %s", file_path)
        try:
            if not self.validate_file(file_path):
                return ""

            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)

            result = json.dumps(data, indent=2, ensure_ascii=False, default=str)
            logger.info("Finished JSON extraction: %s", file_path)
            return result

        except Exception as e:
            logger.error("Error extracting JSON from %s: %s", file_path, str(e))
            return ""
