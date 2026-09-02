"""File identity helpers — single authoritative SHA-256 computation.

Batch 5 §3.3: the audit identified multiple SHA-256 implementations across
the codebase (ai/analysis_manager.py, engines/ai_indexer.py, ui/main_window.py,
widgets/file_explorer.py). This module consolidates them so identity semantics
are consistent: chunked reads, empty-file handling and error behavior.

Empty-file policy (§3.4): an empty file is a *valid* indexed file whose
SHA-256 equals the well-known hash of empty content
(``e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855``).
Exact-duplicate detection reports empty files as an explicit group labelled
"Empty-content duplicates" rather than silently discarding them.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# SHA-256 of zero-length content (documented, deterministic).
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()

CHUNK_SIZE = 65536


class FileIdentityError(Exception):
    """Raised when a file identity cannot be computed."""


def calculate_sha256(path: str, chunk_size: int = CHUNK_SIZE) -> str:
    """Compute the SHA-256 of a file's content.

    Args:
        path: Absolute path to the file.
        chunk_size: Read buffer size (bytes).

    Returns:
        Lowercase hexadecimal SHA-256 digest.

    Raises:
        FileIdentityError: if the file is missing, is a directory, or cannot
            be read (permission denied, I/O error...).
    """
    import os

    if not os.path.exists(path):
        raise FileIdentityError(f"File does not exist: {path}")
    if os.path.isdir(path):
        raise FileIdentityError(f"Path is a directory, not a file: {path}")

    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(chunk_size), b""):
                hasher.update(chunk)
    except OSError as exc:
        raise FileIdentityError(f"Cannot read {path}: {exc}") from exc
    return hasher.hexdigest()


def calculate_sha256_safe(path: str) -> Optional[str]:
    """Compute SHA-256 but return None instead of raising.

    Convenience for callers that treat identity as best-effort (indexing,
    duplicate grouping). Failures are logged at debug level only.
    """
    try:
        return calculate_sha256(path)
    except FileIdentityError as exc:
        logger.debug("SHA-256 unavailable for %s: %s", path, exc)
        return None


def is_empty_sha256(digest: Optional[str]) -> bool:
    """Return True when the digest is the hash of empty content."""
    return bool(digest) and digest == EMPTY_SHA256
