"""Metadata Extraction Service.

Extracts metadata from discovered files using the Folder Scanner output.

No database, UI, text extraction, watcher, or AI dependencies.
"""

from __future__ import annotations

import hashlib
import os
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable

# Platform-specific imports
try:
    import pwd
    HAS_PWD = True
except ImportError:
    HAS_PWD = False


@dataclass
class MetadataResult:
    """Metadata extracted from a file or folder."""
    filename: str
    extension: str
    absolute_path: str
    mime_type: str
    size: int
    created_date: datetime
    modified_date: datetime
    checksum: str
    owner: Optional[str] = None


class MetadataExtractor:
    """Extracts metadata from file system items."""

    def __init__(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_event: Optional["threading.Event"] = None
    ) -> None:
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event

    def process_items(self, items: List["DiscoveredItem"]) -> List[MetadataResult]:
        """Extract metadata from discovered items."""
        results: List[MetadataResult] = []

        for item in items:
            if self.cancel_event and self.cancel_event.is_set():
                continue

            result = self._extract_single(item)
            if result:
                results.append(result)

        return results

    def process_scan(self, scan_results: "ScanResults") -> List[MetadataResult]:
        """Process a Folder Scanner ScanResults and return metadata."""
        return self.process_items(scan_results.items)

    def _extract_single(self, item: "DiscoveredItem") -> Optional[MetadataResult]:
        """Extract metadata for a single discovered item."""
        path = Path(item.path)

        if not path.exists():
            return None

        stat = path.stat()

        # File information
        filename = path.name
        extension = path.suffix.lower() if path.suffix else ""
        absolute_path = str(path.resolve())
        size = item.size if hasattr(item, 'size') else stat.st_size

        # MIME type
        mime_type, _ = mimetypes.guess_type(absolute_path)
        if not mime_type:
            try:
                from engines.config import detect_modality_and_ext
                _, mock_ext = detect_modality_and_ext(absolute_path)
                if mock_ext:
                    mime_type, _ = mimetypes.guess_type(f"dummy{mock_ext}")
            except Exception:
                pass

        # Timestamps
        created_date = datetime.fromtimestamp(stat.st_ctime)
        modified_date = datetime.fromtimestamp(stat.st_mtime)

        # Checksum (only for files)
        checksum = self._calculate_checksum(path) if not item.is_dir else ""

        # Owner information
        owner = self._get_owner(path)

        return MetadataResult(
            filename=filename,
            extension=extension,
            absolute_path=absolute_path,
            mime_type=mime_type or "application/octet-stream",
            size=size,
            created_date=created_date,
            modified_date=modified_date,
            checksum=checksum,
            owner=owner
        )

    def _calculate_checksum(self, path: Path) -> str:
        """Calculate SHA256 checksum of a file."""
        sha256_hash = hashlib.sha256()
        chunk_size = 8192

        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(chunk_size), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except (OSError, IOError):
            return ""

    def _get_owner(self, path: Path) -> Optional[str]:
        """Get file owner information based on platform."""
        try:
            if os.name == 'posix' and HAS_PWD:
                import pwd
                stat = path.stat()
                uid = stat.st_uid
                user_info = pwd.getpwuid(uid)
                return user_info.pw_name
            elif os.name == 'nt':
                return self._get_windows_owner(path)
        except (ImportError, KeyError, OSError):
            pass
        return None

    def _get_windows_owner(self, path: Path) -> Optional[str]:
        """Get owner on Windows using win32security."""
        if not hasattr(self, '_has_win32') or not self._has_win32:
            return None

        try:
            import pywintypes
            import win32security

            security_descriptor = win32security.GetFileSecurity(
                str(path), 
                win32security.OWNER_SECURITY_INFORMATION
            )
            sid = security_descriptor.GetSecurityDescriptorOwner()

            name, domain, typ = win32security.LookupAccountSid(None, sid)

            account_name = name
            if domain:
                account_name = f"{domain}\\{name}"


            return account_name
        except Exception:
            return None

    def batch_process(self, paths: List[str]) -> List[MetadataResult]:
        """Extract metadata for a list of file paths directly."""
        from services.folder_scanner import DiscoveredItem

        items: List[DiscoveredItem] = []

        for path_str in paths:
            path = Path(path_str)
            if path.exists():
                stat = path.stat()
                items.append(
                    DiscoveredItem(
                        path=str(path),
                        name=path.name,
                        parent=str(path.parent),
                        size=stat.st_size if path.is_file() else 0,
                        modified=datetime.fromtimestamp(stat.st_mtime),
                        is_dir=path.is_dir()
                    )
                )

        return self.process_items(items)

    def extract_single_path(self, path: str) -> Optional[MetadataResult]:
        """Extract metadata for a single path."""
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
    ) -> List[MetadataResult]:
        """Scan a directory and extract metadata in one operation."""
        from services.folder_scanner import FolderScanner

        scanner = FolderScanner(
            ignore_patterns=ignore_patterns,
            progress_callback=progress_callback,
            cancel_event=cancel_event
        )

        scan_results = scanner.scan(root_path)
        return self.process_items(scan_results.items)