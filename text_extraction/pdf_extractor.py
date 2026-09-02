"""PDF file extractor using PyMuPDF (fitz)."""

import logging

import fitz

from .base_extractor import BaseExtractor

logger = logging.getLogger(__name__)


class PdfExtractor(BaseExtractor):
    """Extractor for PDF files.

    Uses PyMuPDF (fitz) to extract text content page by page.
    """

    def extract(self, file_path: str) -> str:
        """Extract text from a PDF file.

        Args:
            file_path: Path to the PDF file.

        Returns:
            Extracted text content as a string. Returns empty string on failure.
        """
        logger.info("Starting PDF extraction: %s", file_path)
        try:
            if not self.validate_file(file_path):
                return ""

            text_parts: list[str] = []
            doc = fitz.open(file_path)

            try:
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    page_text = page.get_text()
                    if page_text:
                        text_parts.append(page_text)
                    logger.debug(
                        "Extracted page %d/%d from: %s",
                        page_num + 1,
                        len(doc),
                        file_path,
                    )
            finally:
                doc.close()

            result = "\n".join(text_parts)
            logger.info("Finished PDF extraction: %s", file_path)
            return result

        except Exception as e:
            logger.error("Error extracting PDF from %s: %s", file_path, str(e))
            return ""
