"""Text extraction module for IntelliVault.

Provides extractors for various file formats including PDF, DOCX, XLSX,
PPTX, CSV, JSON, XML, TXT, and Markdown.
"""

from .base_extractor import BaseExtractor
from .extractor_factory import ExtractorFactory

__all__ = ["BaseExtractor", "ExtractorFactory"]
