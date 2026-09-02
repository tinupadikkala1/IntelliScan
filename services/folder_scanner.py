"""Folder Scanner.

Discovers files and folders in a directory tree with progress reporting and
cancellation support. Returns scan results as structured objects without
writing to database or performing metadata/text extraction.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional


@dataclass
class DiscoveredItem:
    path: str
    name: str
    parent: str
    size: int
    modified: datetime
    is_dir: bool


@dataclass
class ScanResults:
    items: List[DiscoveredItem]
    errors: List[str]


def get_item_priority(item: DiscoveredItem) -> int:
    """Return priority rank: 1=Docs, 2=Images, 3=Audio, 4=Video, 5=Other/Dir."""
    if item.is_dir:
        return 5
    ext = Path(item.path).suffix.lower()
    doc_exts = {".pdf", ".docx", ".doc", ".txt", ".md", ".pptx", ".ppt", ".xlsx", ".xls", ".csv", ".rtf", ".odt", ".html", ".htm", ".json", ".xml", ".epub"}
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".tiff", ".tif", ".ico", ".heic"}
    audio_exts = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus", ".m4r"}
    video_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".3gp"}

    if ext in doc_exts:
        return 1
    if ext in image_exts:
        return 2
    if ext in audio_exts:
        return 3
    if ext in video_exts:
        return 4
    return 5


class FolderScanner:
    """Scans a directory tree and reports discovered files/folders."""

    def __init__(
        self,
        ignore_patterns: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        self.ignore_patterns = ignore_patterns or []
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event

    def scan(self, root_path: str) -> ScanResults:
        """Scan the directory tree starting at root_path."""
        root = Path(root_path).resolve()
        items: List[DiscoveredItem] = []
        errors: List[str] = []
        processed = 0

        if not root.exists() or not root.is_dir():
            errors.append(f"Invalid root path: {root_path}")
            return ScanResults(items, errors)

        # First pass: count total entries for progress reporting
        total = self._count_entries(root)
        if total == 0:
            return ScanResults(items, errors)

        # Second pass: actually scan
        try:
            for path in self._walk(root):
                if self.cancel_event and self.cancel_event.is_set():
                    break

                try:
                    stat = path.stat()
                    modified = datetime.fromtimestamp(stat.st_mtime)
                    parent = str(path.parent)
                    name = path.name

                    if path.is_dir():
                        is_dir = True
                        size = 0
                    elif path.is_file():
                        is_dir = False
                        size = stat.st_size
                    else:
                        continue

                    items.append(
                        DiscoveredItem(
                            path=str(path),
                            name=name,
                            parent=parent,
                            size=size,
                            modified=modified,
                            is_dir=is_dir,
                        )
                    )
                    processed += 1
                    if self.progress_callback:
                        self.progress_callback(processed, total)
                except OSError as exc:
                    errors.append(f"Error processing {path}: {exc}")
                    continue
        except OSError as exc:
            errors.append(f"Walk error at {root}: {exc}")

        # Priority sort: 1. Documents -> 2. Images -> 3. Audio -> 4. Video -> 5. Others/Dirs
        items.sort(key=lambda item: (get_item_priority(item), item.path.lower()))

        return ScanResults(items, errors)

    def _count_entries(self, root: Path) -> int:
        """Count total files + folders for progress denominator."""
        count = 0
        try:
            for _ in self._walk(root):
                count += 1
                if self.cancel_event and self.cancel_event.is_set():
                    break
        except OSError:
            pass
        return count

    def _should_ignore(self, path: Path) -> bool:
        """Check if the path should be ignored based on ignore patterns."""
        for pattern in self.ignore_patterns:
            if path.match(pattern) or any(part == pattern for part in path.parts):
                return True
        return False

    def _walk(self, root: Path):
        """Walk directory tree, yielding Path objects.

        Tracks real paths of visited directories to avoid infinite loops
        caused by circular symbolic links.
        """
        seen_dirs: set[str] = set()
        seen_dirs.add(str(root.resolve()))

        for path in root.rglob("*"):
            if self._should_ignore(path):
                continue

            # Skip symlinks that point to non-existent targets
            if path.is_symlink() and not path.exists():
                continue

            # For directories (including symlinked dirs), check for cycles
            if path.is_dir():
                try:
                    real = str(path.resolve())
                except OSError:
                    continue
                if real in seen_dirs:
                    # Circular symlink detected — skip
                    continue
                seen_dirs.add(real)

            yield path