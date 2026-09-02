"""XML file extractor using xml.etree.ElementTree."""

import logging
import xml.etree.ElementTree as ET

from .base_extractor import BaseExtractor

logger = logging.getLogger(__name__)


class XmlExtractor(BaseExtractor):
    """Extractor for XML files.

    Uses ElementTree to extract all text content recursively.
    """

    def extract(self, file_path: str) -> str:
        """Extract text from an XML file.

        Args:
            file_path: Path to the XML file.

        Returns:
            Extracted text content as a string. Returns empty string on failure.
        """
        logger.info("Starting XML extraction: %s", file_path)
        try:
            if not self.validate_file(file_path):
                return ""

            tree = ET.parse(file_path)
            root = tree.getroot()

            text_parts: list[str] = []
            self._extract_text_recursive(root, text_parts)

            result = "\n".join(text_parts)
            logger.info("Finished XML extraction: %s", file_path)
            return result

        except Exception as e:
            logger.error("Error extracting XML from %s: %s", file_path, str(e))
            return ""

    def _extract_text_recursive(
        self, element: ET.Element, text_parts: list[str]
    ) -> None:
        """Recursively extract text from an XML element and its children.

        Args:
            element: The XML element to extract text from.
            text_parts: List to append extracted text to.
        """
        if element.text and element.text.strip():
            text_parts.append(element.text.strip())

        for child in element:
            self._extract_text_recursive(child, text_parts)

        if element.tail and element.tail.strip():
            text_parts.append(element.tail.strip())
