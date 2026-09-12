"""Folder Intelligence dialog — B6-02 (#16) + B7 completion (#31, B7-8).

Entry: right-click a folder → Folder Intelligence…

Sections:
  Overview      — primary category, files analyzed, classified counts
  Statistics    — total files, size, file-type distribution, date range
  File Types    — extension distribution
  AI Summary    — grounded LLM summary (Generate AI Summary button)

Basic statistics work entirely without an LLM; the AI summary is optional
and requires the RAG/LLM layer (explains the prerequisite when absent).
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class FolderIntelligenceDialog(QDialog):
    """Displays folder-level classification composition + statistics."""

    def __init__(
        self,
        folder_path: str,
        service=None,
        on_classify_file: Optional[Callable[[str], None]] = None,
        parent=None,
        intelligence_service=None,
        summary_service=None,
    ) -> None:
        super().__init__(parent)
        self._folder_path = folder_path
        self._service = service
        self._on_classify_file = on_classify_file
        self._intelligence_service = intelligence_service
        self._summary_service = summary_service

        self.setWindowTitle("Folder Statistics")
        self.setMinimumSize(560, 640)
        self.setModal(False)
        self._setup_ui()
        if self._intelligence_service is not None:
            self.stats_label.setVisible(True)
        if self._summary_service is not None:
            self.summary_section.setVisible(True)
        self.refresh()

    # ------------------------------------------------------------------ #
    def set_intelligence_service(self, service) -> None:
        self._intelligence_service = service
        self.stats_label.setVisible(True)

    def set_summary_service(self, service) -> None:
        self._summary_service = service
        self.summary_section.setVisible(True)

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        src = QLabel(f"Folder: {self._folder_path}")
        src.setWordWrap(True)
        src.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(src)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("padding: 6px;")
        layout.addWidget(self.summary_label)

        self.distribution_label = QLabel("")
        self.distribution_label.setWordWrap(True)
        self.distribution_label.setTextInteractionFlags(
            self.distribution_label.textInteractionFlags().TextSelectableByMouse
        )
        self.distribution_label.setStyleSheet(
            "padding: 8px; background: #222; border-radius: 6px; color: #ddd;"
        )
        layout.addWidget(self.distribution_label)

        # Batch 7 (#31): general statistics section (LLM-free).
        self.stats_label = QLabel("")
        self.stats_label.setWordWrap(True)
        self.stats_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.stats_label.setStyleSheet(
            "padding: 8px; background: #1d1d1d; border-radius: 6px; color: #ccc;"
        )
        self.stats_label.setVisible(False)
        layout.addWidget(self.stats_label)

        # Batch 7 (B7-8): AI summary section (hidden until a summary service
        # is attached, so the dialog works with classification alone).
        from PySide6.QtWidgets import QWidget
        self.summary_section = QWidget(self)
        summary_layout = QVBoxLayout(self.summary_section)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_head = QLabel("AI Summary")
        summary_head.setStyleSheet("font-weight: bold; padding-top: 8px;")
        summary_layout.addWidget(summary_head)
        self.ai_summary_label = QLabel("")
        self.ai_summary_label.setWordWrap(True)
        self.ai_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ai_summary_label.setStyleSheet(
            "padding: 8px; background: #222; border-radius: 6px; color: #ddd;"
        )
        summary_layout.addWidget(self.ai_summary_label)
        summary_actions = QHBoxLayout()
        self.summarize_btn = QPushButton("✨ Generate AI Summary")
        self.summarize_btn.clicked.connect(self._on_generate_summary)
        self.copy_summary_btn = QPushButton("Copy")
        self.copy_summary_btn.clicked.connect(self._on_copy_summary)
        summary_actions.addWidget(self.summarize_btn)
        summary_actions.addWidget(self.copy_summary_btn)
        summary_actions.addStretch(1)
        summary_layout.addLayout(summary_actions)
        self.summary_section.setVisible(False)
        layout.addWidget(self.summary_section)
        layout.addStretch(1)

        actions = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(self.refresh_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        """Recompute folder intelligence from the current index and display."""
        self._refresh_classification()
        self._refresh_statistics()
        self._refresh_summary()

    # ------------------------------------------------------------------ #
    def _refresh_classification(self) -> None:
        if self._service is None:
            self.summary_label.setText("Folder classification is not available.")
            self.distribution_label.setText("")
            return
        try:
            info = self._service.classify_folder(self._folder_path)
        except Exception as exc:
            self.summary_label.setText(f"Could not classify folder: {exc}")
            self.distribution_label.setText("")
            return

        total = info.total_files
        if total == 0:
            self.summary_label.setText("No files found in this folder.")
            self.distribution_label.setText(
                "This folder is empty or contains no readable files."
            )
            return

        self.summary_label.setText(
            f"Primary Category: {info.dominant_category or 'other'}\n"
            f"Files Analyzed: {total}  ·  "
            f"Classified: {info.classified_count}  ·  "
            f"Unclassified: {info.unclassified_count}  ·  "
            f"Version: {info.classification_version or '—'}"
        )

        lines = ["Category Distribution:"]
        if not info.distribution:
            lines.append("  (no categories yet — classify files first)")
        else:
            for cat, count in sorted(
                info.distribution.items(), key=lambda kv: kv[1], reverse=True
            ):
                pct = count / total * 100
                bar = "█" * max(1, int(pct / 5))
                lines.append(f"  {cat:<14} {count:>4} ({pct:5.1f}%)  {bar}")
        self.distribution_label.setText("\n".join(lines))

    # ------------------------------------------------------------------ #
    def _refresh_statistics(self) -> None:
        if self._intelligence_service is None:
            return
        try:
            fi = self._intelligence_service.analyze(self._folder_path)
        except Exception as exc:
            self.stats_label.setText(f"Statistics unavailable: {exc}")
            self.stats_label.setVisible(True)
            return
        if fi.total_files == 0:
            self.stats_label.setText("Statistics: no files found in this folder.")
            self.stats_label.setVisible(True)
            return
        from core.file_stat_util import format_file_size
        size_str = format_file_size(fi.total_size, include_exact=True)
        lines = [
            f"Total files: {fi.total_files}  ·  Total size: {size_str}",
            f"Date range: {fi.date_range or '—'}",
            "File types: " + "  ".join(
                f"{k}: {v}" for k, v in sorted(fi.file_type_distribution.items())
            ) if fi.file_type_distribution else "File types: —",
            "Top extensions: " + "  ".join(
                f"{ext or '(none)'}: {n}"
                for ext, n in sorted(fi.extension_distribution.items(),
                                     key=lambda kv: kv[1], reverse=True)[:8]
            ) if fi.extension_distribution else "",
        ]
        if fi.top_keywords:
            lines.append("Top keywords: " + ", ".join(fi.top_keywords))
        if fi.category_distribution:
            lines.append(
                "Top categories: " + ", ".join(
                    f"{c} ({n})"
                    for c, n in sorted(fi.category_distribution.items(),
                                       key=lambda kv: kv[1], reverse=True)[:6]
                )
            )
        self.stats_label.setText("\n".join(lines))
        coverage = []
        if getattr(fi, "unindexed_count", 0):
            coverage.append(f"Not indexed: {fi.unindexed_count}")
        if getattr(fi, "stale_count", 0):
            coverage.append(f"Stale index records: {fi.stale_count}")
        if getattr(fi, "scan_errors", None):
            coverage.append(f"Scan errors: {len(fi.scan_errors)}")
        if coverage:
            self.stats_label.setText(self.stats_label.text() + "\n" + "  ·  ".join(coverage))

    # ------------------------------------------------------------------ #
    def _refresh_summary(self) -> None:
        if self._summary_service is None:
            return
        try:
            persisted = self._summary_service.get(self._folder_path)
        except Exception as exc:
            self.ai_summary_label.setText(f"Summary unavailable: {exc}")
            self.summarize_btn.setText("✨ Generate AI Summary")
            return
        if persisted:
            self.ai_summary_label.setText(persisted["summary"])
            self.summarize_btn.setText("🔄 Regenerate AI Summary")
        else:
            self.ai_summary_label.setText(
                "No AI summary yet. Click 'Generate AI Summary' — this needs "
                "the folder indexed for AI and the local LLM running."
            )
            self.summarize_btn.setText("✨ Generate AI Summary")

    # ------------------------------------------------------------------ #
    def _on_generate_summary(self) -> None:
        if self._summary_service is None:
            return
        self.summarize_btn.setEnabled(False)
        self.ai_summary_label.setText("Generating summary…")
        self.summarize_btn.setText("Generating…")
        try:
            summary = self._summary_service.generate(self._folder_path)
        except Exception as exc:
            self.summarize_btn.setEnabled(True)
            self.summarize_btn.setText("✨ Generate AI Summary")
            self.ai_summary_label.setText(f"Summary generation failed: {exc}")
            return
        self.summarize_btn.setEnabled(True)
        if summary:
            self.ai_summary_label.setText(summary)
            self.summarize_btn.setText("🔄 Regenerate AI Summary")
        else:
            self.ai_summary_label.setText(
                "Summary generation failed — check that the folder is indexed "
                "for AI and the local LLM (Ollama) is running."
            )
            self.summarize_btn.setText("✨ Generate AI Summary")

    # ------------------------------------------------------------------ #
    def _on_copy_summary(self) -> None:
        text = self.ai_summary_label.text()
        if text:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
