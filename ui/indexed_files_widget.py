"""Indexed Files Widget.

Displays indexed files from SQLite with sorting, filtering, selection support.
Connected to existing explorer and database services.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List, Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QComboBox,
    QPushButton,
    QFrame,
    QAbstractItemView,
)
from PySide6.QtCore import Qt, QEvent

from ui.indexed_files_model import IndexedFilesModel

if TYPE_CHECKING:
    from app.container import Container

log = logging.getLogger(__name__)


class IndexedFilesWidget(QWidget):
    """Widget for displaying and managing indexed files from SQLite."""

    def __init__(self, container: Any):
        super().__init__()
        self.container = container
        self.model = IndexedFilesModel(container.db, container.tasks)

        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QLabel("Indexed Files")
        header.setStyleSheet("font-weight: bold; padding: 8px;")
        layout.addWidget(header)

        # Search and filter bar
        search_bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by filename, path, or content...")
        search_bar.addWidget(self.search_input)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All",
            "Images (.png, .jpg, .jpeg, .gif, .bmp, .svg, .webp)",
            "PDF Documents (.pdf)",
            "Text Files (.txt, .md, .py, .json, .yaml, .yml, .csv, .log, .xml, .ini, .toml)",
            "Office Documents (.docx, .xlsx, .pptx)",
            "Audio (.mp3, .flac, .ogg, .wav, .m4a, .aac)",
            "Video (.mp4, .mkv, .mov, .avi, .webm, .m4v)",
            "Archives (.zip, .tar, .gz, .7z, .rar)",
            "Code Files (.py, .js, .ts, .html, .css, .cpp, .java, .rb)",
            "Config Files (.conf, .config, .ini, .yml, .yaml)",
        ])
        self.filter_combo.currentIndexChanged.connect(self._apply_filters)
        search_bar.addWidget(self.filter_combo)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_data)
        search_bar.addWidget(refresh_btn)

        layout.addLayout(search_bar)

        # Files list
        self.files_list = QListWidget()
        self.files_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.files_list.setSortingEnabled(True)
        self.files_list.itemClicked.connect(self._on_file_selected)
        layout.addWidget(self.files_list)

        # Status bar
        self.status_label = QLabel("0 indexed files")
        self.status_label.setAlignment(Qt.AlignLeft)
        layout.addWidget(self.status_label)

    def _setup_connections(self):
        """Set up connections to other components."""
        self.search_input.textChanged.connect(self._apply_search)
        self.model.items_updated.connect(self._on_items_updated)

    def refresh_data(self):
        """Refresh indexed files data from SQLite."""
        log.info("Refreshing indexed files")
        self.model.load_all_items()

    def set_current_path(self, path: str):
        """Set current folder and refresh to show only files from that folder."""
        self.model.set_current_path(path)
        self.model.load_all_items()

    def _apply_filters(self):
        """Apply current filter settings."""
        filter_text = self.filter_combo.currentText()
        self.model.set_filter(filter_text)

    def _apply_search(self):
        """Apply search filter."""
        search_text = self.search_input.text().lower()
        self.model.set_search_text(search_text)

    def _on_items_updated(self, items: List[dict]):
        """Handle updates to the indexed files list."""
        self.files_list.clear()
        for item in items:
            self._add_item_to_list(item)
        self._update_status(len(items))

    def _add_item_to_list(self, item: dict):
        """Add an indexed file to the list display."""
        item_widget, widget = self._create_item_widget(item)
        self.files_list.addItem(item_widget)
        self.files_list.setItemWidget(item_widget, widget)

    def _create_item_widget(self, item: dict):
        """Create a list widget item for an indexed file."""
        item_widget = QListWidgetItem()

        # Create widget for the list item
        widget = QWidget()
        item_layout = QHBoxLayout(widget)
        item_layout.setContentsMargins(4, 4, 4, 4)

        # Icon (placeholder)
        icon_label = QLabel("📄")
        icon_label.setStyleSheet("font-size: 16px;")
        item_layout.addWidget(icon_label)

        # File info
        info_layout = QVBoxLayout()

        # Filename and size
        name_size = QLabel(f"{item['filename']} • {self._get_file_size(item.get('size', 0))}")
        name_size.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(name_size)

        # Path and type
        abs_path = item.get('absolute_path', '')
        display_path = abs_path if len(abs_path) < 60 else abs_path[:57] + '...'
        path_type = QLabel(f"{display_path} • {item.get('mime_type', 'Unknown')}")
        path_type.setStyleSheet("color: gray; font-size: 11px;")
        info_layout.addWidget(path_type)

        # Metadata
        metadata = []
        if item.get('checksum'):
            metadata.append("Checksum")
        if item.get('created_date'):
            metadata.append("Created")
        if item.get('modified_date'):
            metadata.append("Modified")

        metadata_label = QLabel(" • ".join(metadata) if metadata else "No metadata")
        metadata_label.setStyleSheet("color: #666; font-size: 10px;")
        info_layout.addWidget(metadata_label)

        item_layout.addLayout(info_layout)

        # Status
        status = item.get('indexing_status', 'pending')
        status_label = QLabel(status)
        status_label.setStyleSheet(f"color: {'green' if status == 'completed' else 'orange' if status == 'pending' else 'red'}; font-size: 10px;")
        item_layout.addWidget(status_label)

        widget.setLayout(item_layout)
        item_widget.setSizeHint(widget.sizeHint())
        item_widget.setData(Qt.UserRole, item)

        return item_widget, widget

    def _get_file_size(self, size_bytes: int) -> str:
        """Format file size in human readable format."""
        from core.file_stat_util import format_file_size
        return format_file_size(size_bytes)

    def _update_status(self, count: int):
        """Update status label with item count."""
        self.status_label.setText(f"{count} indexed file{'s' if count != 1 else ''}")

    def _on_file_selected(self, item: QListWidgetItem):
        """Handle file selection."""
        item_data = item.data(Qt.UserRole)
        if item_data:
            # Emit signal to main window to open the file
            self.container.bus.file_selected.emit(item_data['absolute_path'])

    def select_item(self, path: str):
        """Select an item by path."""
        for i in range(self.files_list.count()):
            item_widget = self.files_list.item(i)
            if item_widget.data(Qt.UserRole).get('absolute_path') == path:
                self.files_list.setCurrentItem(item_widget)
                self.files_list.scrollToItem(item_widget)
                break