"""Document extractor — wraps existing ContentEngine for text-based files."""

from __future__ import annotations

import logging
from typing import List

from engines.content_engine import ContentBlock, UniversalContentEngine
from .base_extractor import BaseMultimodalExtractor

logger = logging.getLogger(__name__)

_DOC_EXT = {
    '.txt', '.text', '.log', '.md', '.markdown', '.mdown',
    '.json', '.xml', '.xhtml', '.svg',
    '.pdf', '.docx', '.pptx', '.ppt', '.xlsx', '.xls', '.csv', '.tsv',
    '.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.rs', '.go',
    '.html', '.css', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.sh', '.bash', '.bat', '.ps1', '.rb', '.php', '.sql',
}


class DocumentExtractor(BaseMultimodalExtractor):
    """Extracts content from text-based and office documents.

    Delegates to the existing UniversalContentEngine which handles
    PDF, DOCX, PPTX, XLSX, CSV, and plain text formats.
    """

    def __init__(self) -> None:
        self._engine = UniversalContentEngine()

    def supported_extensions(self) -> set:
        return _DOC_EXT

    def extract(self, file_path: str) -> List[ContentBlock]:
        """Extract content blocks from a document.

        Args:
            file_path: Path to the document file.

        Returns:
            List of ContentBlock objects.
        """
        blocks = self._engine.extract(file_path)
        # Enrich with modality
        for block in blocks:
            block.modality = "document"
        return blocks
