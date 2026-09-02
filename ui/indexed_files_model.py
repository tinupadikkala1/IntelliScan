"""Indexed Files Model.

Qt model for displaying indexed files from SQLite with filtering and sorting.
"""

from __future__ import annotations

import os
import logging
import json
from datetime import datetime
from typing import List, Dict, Optional


from PySide6.QtCore import Qt, QObject, QSortFilterProxyModel, Signal

from services.sqlite_indexer import IndexedFile
from database.engine import Database

log = logging.getLogger(__name__)


class IndexedFilesModel(QObject):
    """Qt model for displaying indexed files."""

    items_updated = Signal(list)

    def __init__(self, database: Database, task_manager):
        super().__init__()
        self.database = database
        self.task_manager = task_manager
        self._items: List[Dict] = []
        self._db_session_factory = database.session
        self._filter_text = ""
        self._search_text = ""
        self._current_path = ""

    def set_current_path(self, path: str):
        """Set the current folder path to filter indexed files."""
        self._current_path = path
        self._apply_filters()

    def load_all_items(self):
        """Load indexed files from SQLite for the current folder."""
        try:
            clean_path = os.path.abspath(self._current_path).rstrip("/") if self._current_path else ""
            with self._db_session_factory() as session:
                if clean_path:
                    records = session.query(IndexedFile).filter(
                        IndexedFile.absolute_path.like(clean_path + "/%")
                    ).all()
                    self._items = [
                        self._record_to_dict(record)
                        for record in records
                        if os.path.dirname(record.absolute_path) == clean_path
                    ]
                else:
                    self._items = [self._record_to_dict(record) for record in session.query(IndexedFile).all()]

            self.items_updated.emit(self._items)
            log.info("Loaded %d indexed files for path: %s", len(self._items), clean_path or "(all)")
        except Exception as exc:
            log.error("Failed to load indexed files: %s", exc)
            self.items_updated.emit([])


    def set_filter(self, filter_text: str):
        """Set the MIME type filter."""
        self._filter_text = filter_text.lower()
        self._apply_filters()

    def set_search_text(self, search_text: str):
        """Set the search filter."""
        self._search_text = search_text.lower()
        self._apply_filters()

    def _apply_filters(self):
        """Apply both filter and search filters."""
        filtered_items = self._items.copy()

        # Apply MIME type filter
        if self._filter_text != "all":
            if self._filter_text == "images (.png, .jpg, .jpeg, .gif, .bmp, .svg, .webp)":
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower().startswith('image/')]
            elif self._filter_text == "pdf documents (.pdf)":
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() == 'application/pdf']
            elif self._filter_text == "text files (.txt, .md, .py, .json, .yaml, .yml, .csv, .log, .xml, .ini, .toml)":
                text_mimes = ['text/plain', 'application/json', 'application/x-yaml', 'text/x-yaml',
                             'text/csv', 'application/xml', 'text/plain', 'application/x-ini',
                             'application/x-toml']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in text_mimes]
            elif self._filter_text == "office documents (.docx, .xlsx, .pptx)":
                office_mimes = ['application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                               'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                               'application/vnd.openxmlformats-officedocument.presentationml.presentation']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in office_mimes]
            elif self._filter_text == "audio (.mp3, .flac, .ogg, .wav, .m4a, .aac)":
                audio_mimes = ['audio/mpeg', 'audio/flac', 'audio/ogg', 'audio/wav',
                               'audio/x-m4a', 'audio/aac']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in audio_mimes]
            elif self._filter_text == "video (.mp4, .mkv, .mov, .avi, .webm, .m4v)":
                video_mimes = ['video/mp4', 'video/x-matroska', 'video/quicktime',
                               'video/x-msvideo', 'video/webm', 'video/x-m4v']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in video_mimes]
            elif self._filter_text == "archives (.zip, .tar, .gz, .7z, .rar)":
                archive_mimes = ['application/zip', 'application/x-tar', 'application/gzip',
                                'application/x-7z-compressed', 'application/x-rar-compressed']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in archive_mimes]
            elif self._filter_text == "code files (.py, .js, .ts, .html, .css, .cpp, .java, .rb)":
                code_mimes = ['text/x-python', 'application/javascript', 'application/typescript',
                             'text/html', 'text/css', 'text/x-c++src', 'text/x-java-source',
                             'text/x-ruby']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in code_mimes]
            elif self._filter_text == "config files (.conf, .config, .ini, .yml, .yaml)":
                config_mimes = ['text/plain', 'application/x-yaml', 'text/x-yaml', 'application/x-ini']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in config_mimes]

        # Apply search filter
        if self._search_text:
            filtered_items = [item for item in filtered_items
                            if self._search_text in item.get('filename', '').lower()
                            or self._search_text in item.get('absolute_path', '').lower()
                            or (item.get('extracted_text') and self._search_text in item.get('extracted_text').lower())]

        self.items_updated.emit(filtered_items)

    def get_items(self) -> List[Dict]:
        """Get the current items (after filtering)."""
        return self._items

    def get_filtered_items(self) -> List[Dict]:
        """Get the filtered items."""
        filtered_items = self._items.copy()

        # Apply MIME type filter
        if self._filter_text != "all":
            if self._filter_text == "images (.png, .jpg, .jpeg, .gif, .bmp, .svg, .webp)":
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower().startswith('image/')]
            elif self._filter_text == "pdf documents (.pdf)":
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() == 'application/pdf']
            elif self._filter_text == "text files (.txt, .md, .py, .json, .yaml, .yml, .csv, .log, .xml, .ini, .toml)":
                text_mimes = ['text/plain', 'application/json', 'application/x-yaml', 'text/x-yaml',
                             'text/csv', 'application/xml', 'text/plain', 'application/x-ini',
                             'application/x-toml']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in text_mimes]
            elif self._filter_text == "office documents (.docx, .xlsx, .pptx)":
                office_mimes = ['application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                               'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                               'application/vnd.openxmlformats-officedocument.presentationml.presentation']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in office_mimes]
            elif self._filter_text == "audio (.mp3, .flac, .ogg, .wav, .m4a, .aac)":
                audio_mimes = ['audio/mpeg', 'audio/flac', 'audio/ogg', 'audio/wav',
                               'audio/x-m4a', 'audio/aac']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in audio_mimes]
            elif self._filter_text == "video (.mp4, .mkv, .mov, .avi, .webm, .m4v)":
                video_mimes = ['video/mp4', 'video/x-matroska', 'video/quicktime',
                               'video/x-msvideo', 'video/webm', 'video/x-m4v']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in video_mimes]
            elif self._filter_text == "archives (.zip, .tar, .gz, .7z, .rar)":
                archive_mimes = ['application/zip', 'application/x-tar', 'application/gzip',
                                'application/x-7z-compressed', 'application/x-rar-compressed']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in archive_mimes]
            elif self._filter_text == "code files (.py, .js, .ts, .html, .css, .cpp, .java, .rb)":
                code_mimes = ['text/x-python', 'application/javascript', 'application/typescript',
                             'text/html', 'text/css', 'text/x-c++src', 'text/x-java-source',
                             'text/x-ruby']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in code_mimes]
            elif self._filter_text == "config files (.conf, .config, .ini, .yml, .yaml)":
                config_mimes = ['text/plain', 'application/x-yaml', 'text/x-yaml', 'application/x-ini']
                filtered_items = [item for item in filtered_items
                                if item.get('mime_type', '').lower() in config_mimes]

        # Apply search filter
        if self._search_text:
            filtered_items = [item for item in filtered_items
                            if self._search_text in item.get('filename', '').lower()
                            or self._search_text in item.get('absolute_path', '').lower()
                            or (item.get('extracted_text') and self._search_text in item.get('extracted_text').lower())]

        return filtered_items

    @classmethod
    def _record_to_dict(cls, record: IndexedFile) -> Dict:
        """Convert IndexedFile record to dictionary."""
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
            "last_updated": record.last_updated,
        }