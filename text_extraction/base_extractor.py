"""Base extractor module providing abstract base class for all text extractors."""

import logging
import os
from abc import ABC, abstractmethod

# Configuration
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Abstract base class for text extractors.

    All concrete extractors must inherit from this class and implement
    the extract() method.
    """

    def validate_file(self, file_path: str) -> bool:
        """Validate that a file exists and is within the size limit.

        Args:
            file_path: Path to the file to validate.

        Returns:
            True if the file is valid, False otherwise.
        """
        if not os.path.exists(file_path):
            logger.error("File does not exist: %s", file_path)
            return False

        if not os.path.isfile(file_path):
            logger.error("Path is not a file: %s", file_path)
            return False

        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE:
            logger.error(
                "File exceeds maximum size (%d bytes > %d bytes): %s",
                file_size,
                MAX_FILE_SIZE,
                file_path,
            )
            return False

        if file_size == 0:
            logger.warning("File is empty: %s", file_path)
            return True

        return True

    @abstractmethod
    def extract(self, file_path: str) -> str:
        """Extract text content from a file.

        Args:
            file_path: Path to the file to extract text from.

        Returns:
            Extracted text content as a string. Returns empty string on failure.
        """
        pass
