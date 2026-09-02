"""Semantic Search Dialog.

A standalone dialog for performing semantic (AI-powered) searches across
indexed files — documents, images, audio and video. Displays results with
modality icons, source locations, similarity scores and match-strength
labels. The dialog is purely presentational — it does not import or call any
engine directly. Data flows via signals.
"""

from __future__ import annotations

import os
import time
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

# Modality display metadata ---------------------------------------------- #
_MODALITY_ICONS = {
    "document": "📄",
    "image": "🖼",
    "audio": "🎵",
    "video": "🎬",
}
_MODALITY_FILTERS = [
    ("All", "all"),
    ("Documents", "document"),
    ("Images", "image"),
    ("Audio", "audio"),
    ("Video", "video"),
]

# Match-strength thresholds mirror engines/config.py (documented, not
# calibrated confidence — we only label similarity, never "% confidence").
_SIMILARITY_HIGH = 0.80
_SIMILARITY_MEDIUM = 0.60


def match_strength_label(score: float) -> str:
    """Classify a cosine similarity score into a match-strength label."""
    if score >= _SIMILARITY_HIGH:
        return "High"
    if score >= _SIMILARITY_MEDIUM:
        return "Medium"
    return "Low"


def modality_of(file_path: str, fallback: str = "") -> str:
    """Derive the display modality, trusting the backend modality field first.

    The backend uses magic-byte detection (handles extensionless files).
    Only falls back to extension guessing if no backend modality was provided.
    """
    # Prefer the backend-provided modality (from evidence chunk)
    if fallback and fallback not in ("", "document"):
        return fallback
    if not file_path:
        return fallback or "document"
    # Extension-based fallback for cases where backend modality is missing
    ext = os.path.splitext(file_path)[1].lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif"}:
        return "image"
    if ext in {".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a", ".wma", ".opus"}:
        return "audio"
    if ext in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".wmv"}:
        return "video"
    return fallback or "document"


class SemanticSearchDialog(QDialog):
    """Dialog for semantic search across indexed documents/media.

    Signals:
        file_open_requested: Emitted when a user double-clicks a result
            to open the associated file. Carries the file path.
        search_requested: Emitted when the user submits a search query.
            Carries (query, modality_filter).
        evidence_open_requested: Emitted when a result is double-clicked
            or its Open Evidence button is pressed. Carries the full
            result dict for precise navigation (page/timestamp).
    """

    file_open_requested = Signal(str)
    search_requested = Signal(str, str)  # query, modality filter
    evidence_open_requested = Signal(dict)

    def __init__(self, parent=None) -> None:
        """Initialize the Semantic Search Dialog.

        Args:
            parent: Parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Semantic Search")
        self.setMinimumSize(760, 540)
        self.setModal(False)

        self._start_time: Optional[float] = None
        self._has_searched = False

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the dialog UI layout."""
        layout = QVBoxLayout(self)

        # Search input row
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter semantic search query...")
        self.search_input.returnPressed.connect(self._on_search)
        search_layout.addWidget(self.search_input, 1)

        self.search_button = QPushButton("🔍 Search")
        self.search_button.clicked.connect(self._on_search)
        search_layout.addWidget(self.search_button)

        # Batch 5 §13 — save the current query as a re-runnable search.
        self.save_search_btn = QPushButton("💾 Save Search")
        self.save_search_btn.setToolTip(
            "Save the current query for re-running against the latest index"
        )
        self.save_search_btn.clicked.connect(self._on_save_search)
        search_layout.addWidget(self.save_search_btn)

        self.saved_searches_btn = QPushButton("⭐ Saved Searches")
        self.saved_searches_btn.clicked.connect(self._on_open_saved)
        search_layout.addWidget(self.saved_searches_btn)

        layout.addLayout(search_layout)

        # Filter row — explicit scope filter & modality filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Scope:"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["Current Folder", "Entire System"])
        self.scope_combo.setCurrentIndex(0)  # Current Folder by default
        self.scope_combo.setToolTip("Choose whether to search in the active open folder or across all indexed files")
        self.scope_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.scope_combo)

        filter_layout.addWidget(QLabel("Type:"))
        self.filter_combo = QComboBox()
        for label, _value in _MODALITY_FILTERS:
            self.filter_combo.addItem(label)
        self.filter_combo.setCurrentIndex(0)  # All by default
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.filter_combo)
        filter_layout.addStretch()

        self.status_label = QLabel("Enter a query to search.")
        self.status_label.setStyleSheet("color: gray; padding: 4px;")
        filter_layout.addWidget(self.status_label, 1)

        layout.addLayout(filter_layout)


        # Batch 6 §8.6 — natural-language filter interpretation.
        nl_row = QHBoxLayout()
        self.nl_filters_check = QCheckBox("Parse natural-language filters")
        self.nl_filters_check.setChecked(True)
        self.nl_filters_check.setToolTip(
            "Interpret type / extension / date / size constraints in the query "
            "(e.g. \"PDF files larger than 5 MB\")."
        )
        self.filters_label = QLabel("")
        self.filters_label.setWordWrap(True)
        self.filters_label.setStyleSheet(
            "color: #c9a227; padding: 2px; font-size: 11px;"
        )
        self.clear_filters_btn = QPushButton("✕")
        self.clear_filters_btn.setFixedWidth(28)
        self.clear_filters_btn.setToolTip("Clear parsed filters")
        self.clear_filters_btn.clicked.connect(self._on_clear_filters)
        self.clear_filters_btn.setVisible(False)
        nl_row.addWidget(self.nl_filters_check)
        nl_row.addWidget(self.filters_label, 1)
        nl_row.addWidget(self.clear_filters_btn)
        layout.addLayout(nl_row)

        # Results list
        self.results_list = QListWidget()
        self.results_list.setAlternatingRowColors(True)
        self.results_list.itemDoubleClicked.connect(self._on_result_double_clicked)
        self.results_list.itemActivated.connect(self._on_result_double_clicked)
        layout.addWidget(self.results_list)

    # ------------------------------------------------------------------ #
    @property
    def scope_filter(self) -> str:
        """Return the selected scope filter ('folder' or 'all')."""
        return "folder" if self.scope_combo.currentIndex() == 0 else "all"

    @property
    def modality_filter(self) -> str:
        """Return the selected modality filter value ('all', 'document', ...)."""
        idx = self.filter_combo.currentIndex()
        if 0 <= idx < len(_MODALITY_FILTERS):
            return _MODALITY_FILTERS[idx][1]
        return "all"


    def set_modality_filter(self, value: str) -> None:
        """Set the modality filter by value ('all', 'document', 'image', ...)."""
        for i, (_label, val) in enumerate(_MODALITY_FILTERS):
            if val == value:
                self.filter_combo.setCurrentIndex(i)
                return

    def _on_filter_changed(self) -> None:
        """Re-run the last search when the modality filter changes."""
        query = self.search_input.text().strip()
        if query and self._has_searched:
            # Only auto re-run when a search was already executed.
            self._on_search()

    def _on_search(self) -> None:
        """Handle search button click or Enter key press."""
        query = self.search_input.text().strip()
        if not query:
            return
        self._start_time = time.time()
        self._has_searched = True
        self.status_label.setText("Searching...")
        self.status_label.setStyleSheet("color: gray; padding: 4px;")
        self.results_list.clear()
        self.search_button.setEnabled(False)
        self._show_parsed_filters(query)
        self.search_requested.emit(query, self.modality_filter)

    # Batch 6 §8.6 — show interpreted natural-language filters ---------- #
    def _show_parsed_filters(self, query: str) -> None:
        """Parse the query locally for display (actual filtering happens in
        MainWindow; this is presentational feedback only)."""
        if not self.nl_filters_check.isChecked():
            self.filters_label.setText("")
            self.clear_filters_btn.setVisible(False)
            return
        try:
            from services.nl_filter_parser import describe_filters, parse_query

            parsed = parse_query(query)
            parts = describe_filters(parsed)
            if parts:
                self.filters_label.setText("Filters: " + "  ·  ".join(parts))
                self.clear_filters_btn.setVisible(True)
                self._last_parsed = parsed
            else:
                self.filters_label.setText("")
                self.clear_filters_btn.setVisible(False)
                self._last_parsed = None
        except Exception:
            self.filters_label.setText("")
            self.clear_filters_btn.setVisible(False)
            self._last_parsed = None

    def nl_filters_enabled(self) -> bool:
        """True when natural-language filter parsing is active."""
        return self.nl_filters_check.isChecked()

    def _on_clear_filters(self) -> None:
        """Re-run the search without interpreting NL filters."""
        self.nl_filters_check.setChecked(False)
        self.filters_label.setText("")
        self.clear_filters_btn.setVisible(False)
        query = self.search_input.text().strip()
        if query:
            self._on_search()

    # Batch 5 §13 — Saved searches ----------------------------------- #
    def _on_save_search(self) -> None:
        """Save the current query as a re-runnable saved search."""
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        query = self.search_input.text().strip()
        if not query:
            QMessageBox.information(self, "Save Search", "Enter a query first.")
            return
        name, ok = QInputDialog.getText(
            self, "Save Search", "Name for this saved search:",
            text=query[:40],
        )
        if not ok or not name.strip():
            return
        saved_manager = getattr(self, "_saved_search_manager", None)
        if saved_manager is None:
            QMessageBox.warning(
                self, "Save Search",
                "Saved searches are not available in this context.",
            )
            return
        try:
            # Batch 6 — persist parsed filters with the saved search so the
            # stored query stays the raw NL text (re-parsed on each run).
            filters = {}
            try:
                from services.nl_filter_parser import parse_query

                parsed = parse_query(query)
                filters = parsed.to_dict() if parsed.has_filters else {}
            except Exception:
                filters = {}
            saved_manager.create(
                name=name.strip(),
                query=query,
                scope="workspace",
                scope_path="",
                modality=self.modality_filter,
                filters=filters,
            )
            self.status_label.setText(f"Saved search '{name.strip()}' ✓")
            self.status_label.setStyleSheet("color: green; padding: 4px;")
            saved = getattr(self, "_on_saved_changed", None)
            if saved:
                saved()
        except Exception as exc:
            QMessageBox.warning(self, "Save Search", str(exc))

    def _on_open_saved(self) -> None:
        """Open the Saved Searches dialog (re-run / rename / delete)."""
        from PySide6.QtWidgets import QMessageBox
        from ui.dialogs.saved_searches_dialog import SavedSearchesDialog

        saved_manager = getattr(self, "_saved_search_manager", None)
        if saved_manager is None:
            QMessageBox.warning(
                self, "Saved Searches",
                "Saved searches are not available in this context.",
            )
            return
        dialog = SavedSearchesDialog(saved_manager, on_run=self._on_saved_run, parent=self)
        dialog.run_requested.connect(self._on_saved_run)
        dialog.saved_changed.connect(
            lambda: self._emit_saved_changed()
        )
        dialog.show()

    def _on_saved_run(self, saved) -> None:
        """Run a saved search through the normal search pipeline."""
        self.search_input.setText(saved.query)
        self.set_modality_filter(saved.modality or "all")
        self._has_searched = False  # force re-run on filter change
        self._on_search()
        self.bring_to_front()

    def _emit_saved_changed(self) -> None:
        saved = getattr(self, "_on_saved_changed", None)
        if saved:
            saved()

    def bring_to_front(self) -> None:
        """Raise + focus the dialog (used after launching saved searches)."""
        self.raise_()
        self.activateWindow()

    def set_saved_search_manager(self, manager) -> None:
        """Attach the SavedSearchManager (wired by MainWindow)."""
        self._saved_search_manager = manager

    def set_on_saved_changed(self, callback) -> None:
        """Register a callback fired when a saved search is created/edited."""
        self._on_saved_changed = callback

    def get_query(self) -> str:
        """Return the current search query text.

        Returns:
            The trimmed query string.
        """
        return self.search_input.text().strip()

    def set_results(self, results: list[dict]) -> None:
        """Populate the results list with search results.

        Each result dict should contain:
            - score (float): Relevance score
            - text (str): Text snippet
            - source_label (str): Human-friendly source label
            - file_path (str): Absolute path to the source file
            - modality (str, optional): 'document'/'image'/'audio'/'video'

        Args:
            results: List of result dictionaries.
        """
        self.results_list.clear()
        self.search_button.setEnabled(True)

        elapsed = 0.0
        if self._start_time is not None:
            elapsed = time.time() - self._start_time
            self._start_time = None

        if not results:
            self.status_label.setText(f"No results found ({elapsed:.2f}s)")
            self.status_label.setStyleSheet("color: orange; padding: 4px;")
            return

        for result in results:
            item = self._build_result_item(result)
            self.results_list.addItem(item)

        self.status_label.setText(
            f"{len(results)} result(s) found ({elapsed:.2f}s)"
        )
        self.status_label.setStyleSheet("color: green; padding: 4px;")

    def _build_result_item(self, result: dict) -> QListWidgetItem:
        """Build a rich list item for a single search result."""
        score = result.get("score", 0.0) or 0.0
        text = result.get("text", "")
        source_label = result.get("source_label", "")
        file_path = result.get("file_path", "")
        modality = result.get("modality", "") or modality_of(file_path)
        strength = result.get("match_strength", "") or match_strength_label(score)

        icon = _MODALITY_ICONS.get(modality, "📄")

        # Truncate snippet for display
        snippet = text[:160].replace("\n", " ")
        if len(text) > 160:
            snippet += "..."

        # Source location line (page / slide / timestamp)
        location = ""
        if source_label:
            location = f"  {source_label}"

        display_text = (
            f"{icon} {os.path.basename(file_path) if file_path else '?'}\n"
            f"{location}\n"
            f"  {snippet}\n"
            f"  Similarity: {score:.3f}  ·  Match strength: {strength}"
        )

        item = QListWidgetItem(display_text)
        item.setData(Qt.UserRole, file_path)
        item.setData(Qt.UserRole + 1, result)
        return item

    def set_error(self, error_message: str) -> None:
        """Display an error message in the status label.

        Args:
            error_message: The error description to display.
        """
        self.search_button.setEnabled(True)
        self._start_time = None
        self.status_label.setText(f"Error: {error_message}")
        self.status_label.setStyleSheet("color: red; padding: 4px;")

    def _on_result_double_clicked(self, item: QListWidgetItem) -> None:
        """Handle double-click on a result item.

        Emits the evidence payload (for precise navigation) and the file
        path (for plain opening) so the main window can route correctly.

        Args:
            item: The clicked list widget item.
        """
        file_path = item.data(Qt.UserRole)
        result = item.data(Qt.UserRole + 1) or {}
        if result:
            self.evidence_open_requested.emit(result)
        elif file_path:
            self.file_open_requested.emit(file_path)
