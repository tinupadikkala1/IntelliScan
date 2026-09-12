"""Filesystem-aware folder snapshots shared by folder intelligence services."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from services.path_utils import is_within, norm


@dataclass
class FolderSnapshotEntry:
    path: str
    status: str  # indexed | unindexed | stale | read-error
    size: Optional[int] = None
    modified_date: Optional[datetime] = None
    checksum: Optional[str] = None
    error: Optional[str] = None


@dataclass
class FolderSnapshot:
    folder_path: str
    recursive: bool
    entries: List[FolderSnapshotEntry] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def file_entries(self) -> List[FolderSnapshotEntry]:
        return [e for e in self.entries if e.status in ("indexed", "unindexed")]

    @property
    def stale_entries(self) -> List[FolderSnapshotEntry]:
        return [e for e in self.entries if e.status == "stale"]

    @property
    def status_counts(self) -> Dict[str, int]:
        counts = {"indexed": 0, "unindexed": 0, "stale": 0, "read-error": 0}
        for entry in self.entries:
            counts[entry.status] = counts.get(entry.status, 0) + 1
        return counts


class FolderSnapshotService:
    """Join current disk files with indexed metadata using safe path bounds."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def snapshot(self, folder_path: str, recursive: bool = True) -> FolderSnapshot:
        folder_path = os.path.abspath(folder_path)
        root_key = norm(folder_path)
        indexed: Dict[str, FolderSnapshotEntry] = {}
        errors: List[str] = []

        from services.sqlite_indexer import IndexedFile

        with self._session_factory() as session:
            for row in session.query(IndexedFile).all():
                path = row.absolute_path or ""
                if self._matches(path, folder_path, root_key, recursive):
                    indexed[norm(path)] = FolderSnapshotEntry(
                        path=os.path.abspath(path),
                        status="stale",
                        size=row.size,
                        modified_date=row.modified_date,
                        checksum=row.checksum,
                    )

        disk: Dict[str, FolderSnapshotEntry] = {}
        if os.path.isdir(folder_path):
            self._scan_disk(folder_path, recursive, disk, errors)

        entries: List[FolderSnapshotEntry] = []
        for key, entry in disk.items():
            old = indexed.pop(key, None)
            if entry.status == "read-error":
                if old is not None:
                    entry.checksum = old.checksum
                    entry.size = old.size
                    entry.modified_date = old.modified_date
            elif old is not None:
                entry.status = "indexed"
                entry.checksum = old.checksum
            entries.append(entry)
        entries.extend(indexed.values())
        entries.sort(key=lambda e: e.path.casefold())
        return FolderSnapshot(folder_path, recursive, entries, errors)

    build = snapshot

    @staticmethod
    def _matches(path: str, folder_path: str, root_key: str, recursive: bool) -> bool:
        if not path:
            return False
        path_key = norm(path)
        if recursive:
            return path_key != root_key and is_within(path, folder_path)
        return path_key != root_key and norm(os.path.dirname(path)) == root_key

    def _scan_disk(
        self,
        folder_path: str,
        recursive: bool,
        disk: Dict[str, FolderSnapshotEntry],
        errors: List[str],
    ) -> None:
        pending = [folder_path]
        while pending:
            current = pending.pop()
            try:
                with os.scandir(current) as scan:
                    children = list(scan)
            except OSError as exc:
                errors.append(f"{current}: {exc}")
                continue

            for child in children:
                path = child.path
                try:
                    if child.is_dir(follow_symlinks=False):
                        if recursive:
                            pending.append(path)
                        continue
                    if not child.is_file(follow_symlinks=False):
                        continue
                    stat = child.stat(follow_symlinks=False)
                    disk[norm(path)] = FolderSnapshotEntry(
                        path=os.path.abspath(path),
                        status="unindexed",
                        size=stat.st_size,
                        modified_date=datetime.fromtimestamp(stat.st_mtime),
                    )
                except OSError as exc:
                    errors.append(f"{path}: {exc}")
                    disk[norm(path)] = FolderSnapshotEntry(
                        path=os.path.abspath(path),
                        status="read-error",
                        error=str(exc),
                    )


def build_folder_snapshot(session_factory, folder_path: str, recursive: bool = True) -> FolderSnapshot:
    return FolderSnapshotService(session_factory).snapshot(folder_path, recursive)
