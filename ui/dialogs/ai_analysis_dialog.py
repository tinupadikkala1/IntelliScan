"""AI Analysis Dialog.

Displays the AI-generated analysis results for a file including
summary, category, language, keywords, tags, and generation time.
Also provides option to select detail level, run new analysis, or regenerate.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class AIAnalysisDialog(QDialog):
    """Dialog for displaying and running AI-generated file analysis.

    Supports displaying cached results, running a new analysis, and
    regenerating results at different detail levels.
    """

    regenerate_requested = Signal(str)  # detail_level
    run_analysis_requested = Signal(str)  # detail_level

    def __init__(self, analysis: Optional[dict], file_name: str = "", parent=None) -> None:
        """Initialize the AI Analysis Dialog.

        Args:
            analysis: Optional dict with keys: summary, keywords, tags, category,
                      language, generated_time, model_name, prompt_version.
                      If None or empty, shows the "Run Analysis" view.
            file_name: Display name of the analyzed file.
            parent: Parent widget.
        """
        super().__init__(parent)
        self._analysis = analysis
        self._file_name = file_name

        self.setWindowTitle(f"AI Analysis — {file_name}" if file_name else "AI Analysis")
        self.setMinimumSize(560, 520)
        self.setModal(True)

        self._setup_ui()
        self._populate(analysis)

    def _setup_ui(self) -> None:
        """Set up the dialog UI layout."""
        layout = QVBoxLayout(self)

        # File name header
        if self._file_name:
            header = QLabel(f"<b>{self._file_name}</b>")
            header.setStyleSheet("font-size: 14px; padding: 4px;")
            layout.addWidget(header)

        # Detail Level Selector & Action Header
        options_group = QGroupBox("Analysis Settings")
        options_layout = QHBoxLayout(options_group)

        options_layout.addWidget(QLabel("Detail Level:"))
        self.detail_level_combo = QComboBox()
        self.detail_level_combo.addItems([
            "Low (quick, brief summary)",
            "Medium (balanced detail)",
            "High (comprehensive, detailed)"
        ])
        self.detail_level_combo.setCurrentIndex(1)  # default to Medium
        options_layout.addWidget(self.detail_level_combo, 1)

        layout.addWidget(options_group)

        # Uncached state placeholder
        self.no_analysis_group = QGroupBox("Status")
        no_analysis_layout = QVBoxLayout(self.no_analysis_group)
        self.no_analysis_label = QLabel(
            "No cached AI analysis found for this file.\n\n"
            "Choose a detail level above and click 'Run Analysis' to analyze it."
        )
        self.no_analysis_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_analysis_label.setStyleSheet("color: gray; font-size: 13px; padding: 12px;")
        no_analysis_layout.addWidget(self.no_analysis_label)
        layout.addWidget(self.no_analysis_group)

        # Summary section
        self.summary_group = QGroupBox("Summary")
        summary_layout = QVBoxLayout(self.summary_group)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMaximumHeight(120)
        summary_layout.addWidget(self.summary_text)
        layout.addWidget(self.summary_group)

        # Category & Language row
        self.info_widget = QWidget()
        info_layout = QHBoxLayout(self.info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)

        category_group = QGroupBox("Category")
        cat_layout = QVBoxLayout(category_group)
        self.category_label = QLabel("")
        self.category_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        cat_layout.addWidget(self.category_label)
        info_layout.addWidget(category_group)

        language_group = QGroupBox("Language")
        lang_layout = QVBoxLayout(language_group)
        self.language_label = QLabel("")
        self.language_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        lang_layout.addWidget(self.language_label)
        info_layout.addWidget(language_group)

        layout.addWidget(self.info_widget)

        # Keywords & Tags row
        self.lists_widget = QWidget()
        lists_layout = QHBoxLayout(self.lists_widget)
        lists_layout.setContentsMargins(0, 0, 0, 0)

        keywords_group = QGroupBox("Keywords")
        kw_layout = QVBoxLayout(keywords_group)
        self.keywords_list = QListWidget()
        kw_layout.addWidget(self.keywords_list)
        lists_layout.addWidget(keywords_group)

        tags_group = QGroupBox("Tags")
        tags_layout = QVBoxLayout(tags_group)
        self.tags_list = QListWidget()
        tags_layout.addWidget(self.tags_list)
        lists_layout.addWidget(tags_group)

        layout.addWidget(self.lists_widget)

        # Generation metadata
        self.meta_group = QGroupBox("Generation Info")
        meta_layout = QVBoxLayout(self.meta_group)
        self.generated_time_label = QLabel("")
        self.model_label = QLabel("")
        self.version_label = QLabel("")
        meta_layout.addWidget(self.generated_time_label)
        meta_layout.addWidget(self.model_label)
        meta_layout.addWidget(self.version_label)
        layout.addWidget(self.meta_group)

        # Bottom Buttons
        button_layout = QHBoxLayout()

        self.run_btn = QPushButton("Run Analysis")
        self.run_btn.setStyleSheet("font-weight: bold; background-color: #2a82da; color: white;")
        self.run_btn.clicked.connect(self._on_run_analysis)
        button_layout.addWidget(self.run_btn)

        self.regenerate_btn = QPushButton("Regenerate")
        self.regenerate_btn.clicked.connect(self._on_regenerate)
        button_layout.addWidget(self.regenerate_btn)

        button_layout.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

    def _populate(self, analysis: Optional[dict]) -> None:
        """Populate the dialog widgets with analysis data, or show/hide widgets based on state."""
        if not analysis or "error" in analysis:
            self.no_analysis_group.setVisible(True)
            self.summary_group.setVisible(False)
            self.info_widget.setVisible(False)
            self.lists_widget.setVisible(False)
            self.meta_group.setVisible(False)
            self.regenerate_btn.setVisible(False)
            self.run_btn.setVisible(True)
            return

        self.no_analysis_group.setVisible(False)
        self.summary_group.setVisible(True)
        self.info_widget.setVisible(True)
        self.lists_widget.setVisible(True)
        self.meta_group.setVisible(True)
        self.regenerate_btn.setVisible(True)
        self.run_btn.setVisible(False)

        self.summary_text.setPlainText(analysis.get("summary", ""))
        self.category_label.setText(analysis.get("category", "Unknown"))
        self.language_label.setText(analysis.get("language", "Unknown"))

        # Keywords
        self.keywords_list.clear()
        for kw in analysis.get("keywords", []):
            self.keywords_list.addItem(str(kw))

        # Tags
        self.tags_list.clear()
        for tag in analysis.get("tags", []):
            self.tags_list.addItem(str(tag))

        # Metadata
        gen_time = analysis.get("generated_time")
        if isinstance(gen_time, datetime):
            time_str = gen_time.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(gen_time, str):
            time_str = gen_time
        else:
            time_str = "Unknown"

        self.generated_time_label.setText(f"Generated: {time_str}")
        self.model_label.setText(f"Model: {analysis.get('model_name', 'Unknown')}")
        self.version_label.setText(f"Prompt Version: {analysis.get('prompt_version', 'Unknown')}")

    def _get_selected_level(self) -> str:
        """Helper to get selected detail level string."""
        idx = self.detail_level_combo.currentIndex()
        if idx == 0:
            return "low"
        elif idx == 2:
            return "high"
        return "medium"

    def _on_run_analysis(self) -> None:
        """Handle 'Run Analysis' button click."""
        self.run_analysis_requested.emit(self._get_selected_level())

    def _on_regenerate(self) -> None:
        """Handle 'Regenerate' button click."""
        self.regenerate_requested.emit(self._get_selected_level())

    def update_analysis(self, analysis: dict) -> None:
        """Update the displayed analysis with new data."""
        self._analysis = analysis
        self._populate(analysis)
