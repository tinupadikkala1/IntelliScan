"""Extractor factory for mapping file extensions to appropriate extractors."""

import logging
import os
from typing import Optional

from .base_extractor import BaseExtractor
from .csv_extractor import CsvExtractor
from .docx_extractor import DocxExtractor
from .json_extractor import JsonExtractor
from .md_extractor import MdExtractor
from .pdf_extractor import PdfExtractor
from .pptx_extractor import PptxExtractor
from .txt_extractor import TxtExtractor
from .xlsx_extractor import XlsxExtractor
from .xml_extractor import XmlExtractor

logger = logging.getLogger(__name__)


class ExtractorFactory:
    """Factory class for creating appropriate text extractors based on file extension.

    Maps file extensions to their corresponding extractor classes.
    Supports multiple extensions per file type.
    """

    _extension_map: dict[str, type[BaseExtractor]] = {
        # Plain text
        ".txt": TxtExtractor,
        ".text": TxtExtractor,
        ".log": TxtExtractor,
        # Markdown
        ".md": MdExtractor,
        ".markdown": MdExtractor,
        ".mdown": MdExtractor,
        # PDF
        ".pdf": PdfExtractor,
        # Microsoft Word
        ".docx": DocxExtractor,
        # Microsoft Excel
        ".xlsx": XlsxExtractor,
        ".xls": XlsxExtractor,
        # Microsoft PowerPoint
        ".pptx": PptxExtractor,
        ".ppt": PptxExtractor,
        # CSV
        ".csv": CsvExtractor,
        ".tsv": CsvExtractor,
        # JSON
        ".json": JsonExtractor,
        # XML
        ".xml": XmlExtractor,
        ".xhtml": XmlExtractor,
        ".svg": XmlExtractor,
    }

    @classmethod
    def get_extractor(cls, file_path: str) -> Optional[BaseExtractor]:
        """Get the appropriate extractor for a given file path.

        Args:
            file_path: Path to the file to extract text from.

        Returns:
            An instance of the appropriate BaseExtractor subclass,
            or None if the file type is not supported.
        """
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()

        extractor_class = cls._extension_map.get(ext)

        if extractor_class is None:
            logger.warning(
                "No extractor found for extension '%s': %s", ext, file_path
            )
            return None

        logger.debug(
            "Using %s for file: %s", extractor_class.__name__, file_path
        )
        return extractor_class()

    @classmethod
    def supported_extensions(cls) -> list[str]:
        """Get a list of all supported file extensions.

        Returns:
            List of supported file extensions (e.g., ['.txt', '.pdf', ...]).
        """
        return sorted(cls._extension_map.keys())
