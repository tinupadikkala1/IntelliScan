"""SQLite Indexing Service.

Stores metadata, extracted text, checksums, scan timestamps, and indexing status.

No UI, no watcher dependencies.
"""

from __future__ import annotations

import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, Text

from database.models import Base
from services.folder_scanner import DiscoveredItem
from services.metadata_extractor import MetadataResult
from services.text_extractor import ExtractionResult


class IndexingStatus(Enum):
    """Enum to track indexing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class IndexedFile(Base):
    """Table to store indexed file information."""
    __tablename__ = "indexed_files"

    id = Column(Integer, primary_key=True)
    filename = Column(Text, nullable=False)
    absolute_path = Column(Text, unique=True, nullable=False)
    size = Column(Integer)
    mime_type = Column(Text)
    extension = Column(Text)
    created_date = Column(DateTime)
    modified_date = Column(DateTime)
    checksum = Column(Text)
    extracted_text = Column(Text)
    metadata_json = Column(Text)
    # Batch 7: user-edited metadata (B7-6) — kept separate from AI-generated
    # values so manual edits never silently overwrite AI analysis.
    user_metadata_json = Column(Text)
    scan_timestamp = Column(DateTime, default=datetime.utcnow)
    indexing_status = Column(Text, default=IndexingStatus.PENDING.value)
    processing_attempts = Column(Integer, default=0)
    error_message = Column(Text)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_opened_at = Column(DateTime)



class SQLiteIndexer:
    """Indexes files using SQLite, integrating with metadata and text extraction services."""

    def __init__(
        self,
        session_factory,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_event: Optional[threading.Event] = None
    ) -> None:
        self.session_factory = session_factory
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event

    def index_items(
        self,
        items: List[DiscoveredItem],
        metadata_results: List[MetadataResult],
        text_results: List[ExtractionResult]
    ) -> List[dict]:
        """Index discovered items with metadata and extracted text."""
        results = []
        total = len(items)

        # Build dictionaries to avoid O(N^2) linear search in loops
        metadata_lookup = {meta.absolute_path: meta for meta in metadata_results}
        text_lookup = {text.absolute_path: text for text in text_results}

        with self.session_factory() as session:
            # Batch query existing files in SQLite to avoid N+1 queries
            paths = [item.path for item in items]
            existing_records = {}
            chunk_size = 500
            for i in range(0, len(paths), chunk_size):
                chunk_paths = paths[i:i+chunk_size]
                records = session.query(IndexedFile).filter(IndexedFile.absolute_path.in_(chunk_paths)).all()
                for r in records:
                    existing_records[r.absolute_path] = r

            for idx, item in enumerate(items):
                if self.cancel_event and self.cancel_event.is_set():
                    break

                indexed = self._index_single(
                    session, item, idx, total, metadata_lookup, text_lookup, existing_records
                )
                results.append(indexed)

            session.commit()

        return results

    def _get_metadata_for_item(
        self,
        item: DiscoveredItem,
        metadata_lookup: List[MetadataResult] | dict[str, MetadataResult]
    ) -> MetadataResult:
        """Get or create metadata result for a discovered item."""
        if isinstance(metadata_lookup, dict):
            if item.path in metadata_lookup:
                return metadata_lookup[item.path]
        else:
            for meta in metadata_lookup:
                if meta.absolute_path == item.path:
                    return meta

        path = Path(item.path)
        return MetadataResult(
            filename=path.name,
            extension=path.suffix.lower() if path.suffix else "",
            absolute_path=str(path.resolve()),
            mime_type="application/octet-stream",
            size=item.size,
            created_date=(
                __import__("core.file_stat_util", fromlist=["get_file_creation_date"]).get_file_creation_date(str(path.resolve()))
                or datetime.fromtimestamp(path.stat().st_ctime)
            ),
            modified_date=datetime.fromtimestamp(path.stat().st_mtime),
            checksum="",
            owner=None
        )

    def _get_text_for_item(
        self,
        item: DiscoveredItem,
        text_lookup: List[ExtractionResult] | dict[str, ExtractionResult]
    ) -> ExtractionResult:
        """Get or create extracted text result for a discovered item."""
        if isinstance(text_lookup, dict):
            if item.path in text_lookup:
                return text_lookup[item.path]
        else:
            for text in text_lookup:
                if text.absolute_path == item.path:
                    return text

        path = Path(item.path)
        return ExtractionResult(
            filename=path.name,
            absolute_path=str(path.resolve()),
            text=f"Directory: {path.name}" if item.is_dir else "",
            format=path.suffix.lower() if path.suffix else "",
            word_count=0,
            char_count=0,
            line_count=0
        )

    def _index_single(
        self,
        session,
        item: DiscoveredItem,
        index: int,
        total: int,
        metadata_lookup: List[MetadataResult] | dict[str, MetadataResult],
        text_lookup: List[ExtractionResult] | dict[str, ExtractionResult],
        existing_records: Optional[dict[str, IndexedFile]] = None
    ) -> dict:
        """Index a single item and persist to SQLite."""
        # Update progress callback
        if self.progress_callback:
            self.progress_callback(index + 1, total)

        try:
            metadata = self._get_metadata_for_item(item, metadata_lookup)
            text = self._get_text_for_item(item, text_lookup)

            # Check if record already exists (using batch cache if available)
            existing = None
            if existing_records is not None:
                existing = existing_records.get(metadata.absolute_path)
            else:
                existing = session.query(IndexedFile).filter_by(
                    absolute_path=metadata.absolute_path
                ).first()

            if existing:
                existing.filename = metadata.filename
                existing.size = metadata.size
                existing.mime_type = metadata.mime_type
                existing.extension = metadata.extension
                existing.created_date = metadata.created_date
                existing.modified_date = metadata.modified_date
                existing.checksum = metadata.checksum
                existing.extracted_text = text.text
                existing.scan_timestamp = datetime.utcnow()
                existing.indexing_status = IndexingStatus.COMPLETED.value
                existing.last_updated = datetime.utcnow()
                record = existing
            else:
                record = IndexedFile(
                    filename=metadata.filename,
                    absolute_path=metadata.absolute_path,
                    size=metadata.size,
                    mime_type=metadata.mime_type,
                    extension=metadata.extension,
                    created_date=metadata.created_date,
                    modified_date=metadata.modified_date,
                    checksum=metadata.checksum,
                    extracted_text=text.text,
                    metadata_json="",
                    scan_timestamp=datetime.utcnow(),
                    indexing_status=IndexingStatus.COMPLETED.value,
                    processing_attempts=0,
                    error_message=None,
                    last_updated=datetime.utcnow(),
                )
                session.add(record)

            return {
                "path": metadata.absolute_path,
                "filename": metadata.filename,
                "status": IndexingStatus.COMPLETED.value,
                "size": metadata.size,
                "error": None,
            }
        except Exception as exc:
            logger.error("Failed to index item %s: %s", getattr(item, 'path', 'unknown'), exc)
            abs_path = str(Path(item.path).resolve()) if hasattr(item, 'path') else 'unknown'
            fname = Path(abs_path).name
            existing = session.query(IndexedFile).filter_by(absolute_path=abs_path).first()
            if existing:
                existing.indexing_status = IndexingStatus.FAILED.value
                existing.error_message = str(exc)
            else:
                session.add(IndexedFile(
                    filename=fname,
                    absolute_path=abs_path,
                    size=getattr(item, 'size', 0),
                    mime_type="application/octet-stream",
                    extension=Path(abs_path).suffix.lower(),
                    scan_timestamp=datetime.utcnow(),
                    indexing_status=IndexingStatus.FAILED.value,
                    processing_attempts=1,
                    error_message=str(exc),
                    last_updated=datetime.utcnow(),
                ))
            return {
                "path": abs_path,
                "filename": fname,
                "status": IndexingStatus.FAILED.value,
                "size": getattr(item, 'size', 0),
                "error": str(exc),
            }




    def index_scan(
        self,
        scan_results: ScanResults,
        metadata_extractor,
        text_extractor,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_event: Optional[threading.Event] = None
    ) -> List[dict]:
        """Perform a complete scan and indexing operation."""
        items = scan_results.items
        total = len(items)

        # Extract metadata for all items
        metadata_results = metadata_extractor.process_items(items)

        # Extract text for all items
        text_results = text_extractor.process_items(items)

        # Index all items together
        return self.index_items(items, metadata_results, text_results)

    def get_by_path(self, absolute_path: str) -> Optional[dict]:
        """Look up indexed record by absolute path."""
        with self.session_factory() as session:
            record = session.query(IndexedFile).filter_by(absolute_path=absolute_path).first()
            return self._record_to_dict(record) if record else None

    def get_by_filename(self, filename: str) -> List[dict]:
        """Look up indexed records by filename."""
        with self.session_factory() as session:
            records = session.query(IndexedFile).filter_by(filename=filename).all()
            return [self._record_to_dict(r) for r in records]

    def update_indexed_record(self, absolute_path: str, updates: dict) -> bool:
        """Update an indexed record."""
        with self.session_factory() as session:
            record = session.query(IndexedFile).filter_by(absolute_path=absolute_path).first()
            if not record:
                return False

            for key, value in updates.items():
                if hasattr(record, key):
                    setattr(record, key, value)

            record.last_updated = datetime.utcnow()
            session.commit()
            return True

    def delete_indexed_record(self, absolute_path: str) -> bool:
        """Delete an indexed record."""
        with self.session_factory() as session:
            record = session.query(IndexedFile).filter_by(absolute_path=absolute_path).first()
            if not record:
                return False

            session.delete(record)
            session.commit()
            return True

    def list_indexed_records(self, limit: Optional[int] = None) -> List[dict]:
        """List all indexed records."""
        with self.session_factory() as session:
            query = session.query(IndexedFile)
            if limit:
                query = query.limit(limit)

            records = query.all()
            return [self._record_to_dict(r) for r in records]

    def _record_to_dict(self, record: IndexedFile) -> dict:
        """Convert IndexedFile record to dictionary."""
        if not record:
            return {}

        return {
            "id": record.id,
            "filename": record.filename,
            "absolute_path": record.absolute_path,
            "size": record.size,
            "mime_type": record.mime_type,
            "extension": record.extension,
            "created_date": record.created_date,
            "modified_date": record.modified_date,
            "checksum": record.checksum,
            "extracted_text": record.extracted_text,
            "metadata_json": record.metadata_json,
            "scan_timestamp": record.scan_timestamp,
            "indexing_status": record.indexing_status,
            "processing_attempts": record.processing_attempts,
            "error_message": record.error_message,
            "last_updated": record.last_updated
        }

    def index_new_files(
        self,
        new_paths: List[str],
        root_path: str
    ) -> List[dict]:
        """Index only new files, comparing against existing index."""
        with self.session_factory() as session:
            existing_paths = {
                r.absolute_path for r in session.query(IndexedFile.absolute_path).all()
            }

        new_to_index = []
        for path_str in new_paths:
            path = Path(path_str)
            if not path.is_absolute():
                path = Path(root_path).resolve() / path

            if str(path) not in existing_paths:
                new_to_index.append(path)

        if not new_to_index:
            return []

        from services.folder_scanner import DiscoveredItem

        items: List[DiscoveredItem] = []
        for path in new_to_index:
            if path.exists():
                try:
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
                except OSError:
                    continue

        # Use the existing index_items method
        return self.index_items(items, [], [])

    def batch_update_status(
        self,
        updates: List[dict]
    ) -> int:
        """Batch update indexing status for multiple records."""
        updated_count = 0

        with self.session_factory() as session:
            for update_data in updates:
                absolute_path = update_data.get("absolute_path")
                if not absolute_path:
                    continue

                record = session.query(IndexedFile).filter_by(absolute_path=absolute_path).first()
                if record:
                    if "indexing_status" in update_data:
                        record.indexing_status = update_data["indexing_status"]
                    if "error_message" in update_data:
                        record.error_message = update_data["error_message"]
                    if "processing_attempts" in update_data:
                        record.processing_attempts = update_data["processing_attempts"]
                    record.last_updated = datetime.utcnow()
                    updated_count += 1

            session.commit()

        return updated_count

    def get_indexing_stats(self) -> dict:
        """Get statistics about indexed files."""
        with self.session_factory() as session:
            total_count = session.query(IndexedFile).count()
            pending_count = session.query(IndexedFile).filter_by(indexing_status=IndexingStatus.PENDING.value).count()
            completed_count = session.query(IndexedFile).filter_by(indexing_status=IndexingStatus.COMPLETED.value).count()
            failed_count = session.query(IndexedFile).filter_by(indexing_status=IndexingStatus.FAILED.value).count()

            return {
                "total": total_count,
                "pending": pending_count,
                "completed": completed_count,
                "failed": failed_count,
                "completion_rate": (completed_count / total_count * 100) if total_count > 0 else 0.0
            }

    def cleanup_indexed_files(self, older_than_days: int = 30) -> int:
        """Remove indexed files older than specified days."""
        cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)

        with self.session_factory() as session:
            older_files = session.query(IndexedFile).filter(
                IndexedFile.last_updated < cutoff_date
            ).all()

            for file in older_files:
                session.delete(file)

            session.commit()
            return len(older_files)

    def reindex_file(self, absolute_path: str) -> Optional[dict]:
        """Reindex a specific file."""
        from services.folder_scanner import DiscoveredItem

        path = Path(absolute_path)
        if not path.exists():
            return None

        from services.metadata_extractor import MetadataExtractor
        from services.text_extractor import TextExtractor

        metadata_extractor = MetadataExtractor()
        text_extractor = TextExtractor()

        metadata = metadata_extractor.extract_single_path(absolute_path)
        if not metadata:
            return None

        text = text_extractor.extract_single_path(absolute_path)

        item = DiscoveredItem(
            path=absolute_path,
            name=path.name,
            parent=str(path.parent),
            size=metadata.size,
            modified=metadata.modified_date,
            is_dir=path.is_dir()
        )

        with self.session_factory() as session:
            result = self._index_single(session, item, 0, 1, [metadata], [text] if text else [])
            session.commit()

        return result


# For type hints
from datetime import timedelta
from services.folder_scanner import ScanResults