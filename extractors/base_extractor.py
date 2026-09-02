"""Base extractor interface for multimodal content extraction."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import List

from engines.content_engine import ContentBlock


class BaseMultimodalExtractor(ABC):
    """Abstract base class for all multimodal extractors.

    All extractors must implement extract(path) -> list[ContentBlock].
    """

    @abstractmethod
    def extract(self, file_path: str) -> List[ContentBlock]:
        """Extract content blocks from a file.

        Args:
            file_path: Absolute path to the file.

        Returns:
            List of ContentBlock objects with extracted content.
        """
        ...

    @abstractmethod
    def supported_extensions(self) -> set:
        """Return set of supported file extensions (lowercase, with dot).

        Returns:
            Set of extension strings, e.g. {'.png', '.jpg'}.
        """
        ...

    def can_handle(self, file_path: str) -> bool:
        """Check if this extractor can handle the given file.

        Args:
            file_path: Path to check.

        Returns:
            True if the file extension is supported.
        """
        ext = os.path.splitext(file_path)[1].lower()
        return ext in self.supported_extensions()
