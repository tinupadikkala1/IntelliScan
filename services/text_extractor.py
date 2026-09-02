"""Text Extraction Service.

Extracts text content from supported document formats.

No database, UI, text storage, watcher, or AI dependencies.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable

log = logging.getLogger(__name__)

# Optional dependencies
try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    import pptx
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False

try:
    import openpyxl
    HAS_OPENPYX = True
except ImportError:
    HAS_OPENPYX = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


def safe_read_file(path: Path, encoding: str = "utf-8", errors: str = "replace") -> str:
    """Read file content safely with fallback encoding."""
    try:
        with open(path, "r", encoding=encoding, errors=errors) as f:
            return f.read()
    except Exception as exc:
        log.debug(f"Failed to read {path} with {encoding}: {exc}")
        return ""


@dataclass
class ExtractionResult:
    """Result of text extraction from a file."""
    filename: str
    absolute_path: str
    text: str
    format: str
    word_count: int
    char_count: int
    line_count: int


class TextExtractor:
    """Extracts text from various document formats."""

    # Default maximum file size for text extraction (20 MB)
    DEFAULT_MAX_FILE_SIZE = 20 * 1024 * 1024

    def __init__(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_event: Optional["threading.Event"] = None,
        max_file_size: Optional[int] = None,
    ) -> None:
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event
        self.max_file_size = max_file_size if max_file_size is not None else self.DEFAULT_MAX_FILE_SIZE

    def process_items(
        self,
        items: List["DiscoveredItem"]
    ) -> List[ExtractionResult]:
        """Extract text from discovered items."""
        results: List[ExtractionResult] = []

        for item in items:
            if self.cancel_event and self.cancel_event.is_set():
                continue

            result = self._extract_single(item)
            if result:
                results.append(result)

        return results

    def process_scan(self, scan_results: "ScanResults") -> List[ExtractionResult]:
        """Process a Folder Scanner ScanResults and extract text."""
        return self.process_items(scan_results.items)

    def _extract_single(self, item: "DiscoveredItem") -> Optional[ExtractionResult]:
        """Extract text from a single discovered item."""
        path = Path(item.path)

        if not path.exists():
            return None

        # Skip files exceeding the maximum size limit
        if not item.is_dir and item.size > self.max_file_size:
            log.debug(f"Skipping {path}: file size {item.size} exceeds limit {self.max_file_size}")
            return None

        text = ""
        file_format = self._detect_format(path)

        try:
            if file_format == "pdf" and HAS_PYPDF2:
                text = self._extract_pdf_text(path)
            elif file_format == "docx" and HAS_DOCX:
                text = self._extract_docx_text(path)
            elif file_format == "txt":
                text = safe_read_file(path)
            elif file_format == "md":
                text = safe_read_file(path)
            elif file_format == "csv":
                text = self._extract_csv_text(path)
            elif file_format == "xlsx":
                text = self._extract_excel_text(path)
            elif file_format == "pptx" and HAS_PPTX:
                text = self._extract_pptx_text(path)
            elif item.is_dir:
                text = f"Directory: {path.name}"
            else:
                log.debug(f"Non-text or binary format for {path}: {file_format}")
                text = ""

            return ExtractionResult(
                filename=path.name,
                absolute_path=str(path.resolve()),
                text=text,
                format=file_format or (path.suffix.lower() if path.suffix else ""),
                word_count=len(text.split()) if text else 0,
                char_count=len(text) if text else 0,
                line_count=len(text.splitlines()) if text else 0
            )
        except Exception as exc:
            log.debug(f"Failed to extract text from {path}: {exc}")
            return ExtractionResult(
                filename=path.name,
                absolute_path=str(path.resolve()),
                text="",
                format=path.suffix.lower() if path.suffix else "",
                word_count=0,
                char_count=0,
                line_count=0
            )


    def _detect_format(self, path: Path) -> str:
        """Detect the format of a file based on extension."""
        ext = path.suffix.lower()
        format_map = {
            ".pdf": "pdf",
            ".docx": "docx",
            ".txt": "txt",
            ".md": "md",
            ".markdown": "md",
            ".csv": "csv",
            ".xlsx": "xlsx",
            ".pptx": "pptx",
            ".xls": "xlsx",
            ".ppt": "pptx",
        }
        return format_map.get(ext, "")

    def _extract_pdf_text(self, path: Path) -> str:
        """Extract text from PDF."""
        text = ""
        try:
            with open(path, "rb") as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except Exception as exc:
            log.debug(f"PDF extraction failed for {path}: {exc}")
        return text

    def _extract_docx_text(self, path: Path) -> str:
        """Extract text from DOCX."""
        try:
            doc = docx.Document(path)
            return "\n".join(paragraph.text for paragraph in doc.paragraphs)
        except Exception as exc:
            log.debug(f"DOCX extraction failed for {path}: {exc}")
            return ""

    def _extract_csv_text(self, path: Path) -> str:
        """Extract text from CSV."""
        try:
            if HAS_PANDAS:
                df = pd.read_csv(path)
                return df.to_string()
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return "\n".join(line.strip() for line in f)
        except Exception as exc:
            log.debug(f"CSV extraction failed for {path}: {exc}")
            return ""

    def _extract_excel_text(self, path: Path) -> str:
        """Extract text from Excel."""
        try:
            if HAS_PANDAS:
                df = pd.read_excel(path)
                return df.to_string()
            elif HAS_OPENPYX:
                wb = openpyxl.load_workbook(path)
                text_parts = []
                for ws in wb.worksheets:
                    for row in ws.iter_rows(values_only=True):
                        text_parts.append(str(row).strip())
                return "\n".join(text_parts)
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
        except Exception as exc:
            log.debug(f"Excel extraction failed for {path}: {exc}")
            return ""

    def _extract_pptx_text(self, path: Path) -> str:
        """Extract text from PPTX."""
        try:
            prs = pptx.Presentation(path)
            text_parts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text_frame") and shape.text_frame:
                        for paragraph in shape.text_frame.paragraphs:
                            text_parts.append(paragraph.text)
            return "\n".join(text_parts)
        except Exception as exc:
            log.debug(f"PPTX extraction failed for {path}: {exc}")
            return ""

    def extract_single_path(self, path: str) -> Optional[ExtractionResult]:
        """Extract text from a single path."""
        from services.folder_scanner import DiscoveredItem

        try:
            item_path = Path(path)
            if not item_path.exists():
                return None

            stat = item_path.stat()
            item = DiscoveredItem(
                path=str(item_path),
                name=item_path.name,
                parent=str(item_path.parent),
                size=stat.st_size if item_path.is_file() else 0,
                modified=datetime.fromtimestamp(stat.st_mtime),
                is_dir=item_path.is_dir()
            )

            results = self.process_items([item])
            return results[0] if results else None
        except Exception:
            return None

    def scan_and_extract(
        self,
        root_path: str,
        ignore_patterns: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_event: Optional["threading.Event"] = None
    ) -> List[ExtractionResult]:
        """Scan a directory and extract text in one operation."""
        from services.folder_scanner import FolderScanner

        scanner = FolderScanner(
            ignore_patterns=ignore_patterns,
            progress_callback=progress_callback,
            cancel_event=cancel_event
        )

        scan_results = scanner.scan(root_path)
        return self.process_items(scan_results.items)

    def extract_text_only(self, result: ExtractionResult) -> str:
        """Extract just the text from an ExtractionResult."""
        return result.text


# For type hints (circular dependency resolution)
from services.folder_scanner import DiscoveredItem, ScanResults