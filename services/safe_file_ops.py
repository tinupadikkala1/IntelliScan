"""Safe, reversible file operations — B6-04 / B6-05.

Batch 6 never permanently deletes user files without approval. When an
approved operation removes a file (smart duplicate removal), the file is
moved into the application's *reversible trash* directory instead of being
erased, and the index is synchronized through the existing cleanup path.

    approve
      ↓ move file → config/trash/<timestamp>/<name>
      ↓ cleanup_deleted_file(src)  (indexed row, evidence, vectors, graph,
        relationships, collections, suggestions)
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Keep in sync with engines/config TRASH_DIR default.
DEFAULT_TRASH_DIR = "config/trash"


@dataclass
class SafeFileOpResult:
    """Outcome of a reversible file operation."""

    ok: bool
    action: str = ""            # trashed | moved
    source: str = ""
    target: str = ""            # new location (trash path or destination)
    error: str = ""


class FileOperationError(Exception):
    """Raised for user-facing file-operation failures."""


def _resolve_trash_dir(trash_dir: Optional[str]) -> str:
    if trash_dir and os.path.isabs(trash_dir):
        return trash_dir
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
    rel = trash_dir or DEFAULT_TRASH_DIR
    return os.path.abspath(os.path.join(base, rel))


def move_to_trash(
    path: str,
    trash_dir: Optional[str] = None,
    session_factory=None,
    retrieval=None,
    db_store=None,
    graph_engine=None,
    vector_engine=None,
) -> SafeFileOpResult:
    """Move a file into the reversible app trash and synchronize the index.

    The file is *never* permanently deleted; the trash directory is a plain
    folder the user can browse to recover anything. The index is updated via
    the existing orchestrated cleanup so no stale derived state remains.

    Returns SafeFileOpResult. Raises FileOperationError on validation failure
    (missing source, source==target, permission denied).
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileOperationError(f"The file no longer exists: {path}")

    trash_root = _resolve_trash_dir(trash_dir)
    try:
        os.makedirs(trash_root, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_dir = os.path.join(trash_root, stamp)
        os.makedirs(dest_dir, exist_ok=True)
        target = os.path.join(dest_dir, os.path.basename(path))
        shutil.move(path, target)
    except OSError as exc:
        raise FileOperationError(f"Cannot move file to trash: {exc}") from exc

    # Synchronize every derived layer through the orchestrated cleanup path.
    try:
        from services.file_cleanup import cleanup_deleted_file

        cleanup_deleted_file(
            abs_path=path,
            session_factory=session_factory,
            retrieval=retrieval,
            db_store=db_store,
            graph_engine=graph_engine,
            vector_engine=vector_engine,
        )
    except Exception as exc:
        logger.error("Trash move succeeded but sync failed for %s: %s", path, exc)

    logger.info("Trashed %s → %s", path, target)
    return SafeFileOpResult(
        ok=True,
        action="trashed",
        source=path,
        target=target,
    )
