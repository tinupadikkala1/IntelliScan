"""Document Comparison dialog — B7-5 (#21).

Entry: Tools → Compare Documents.

Pick Document A and Document B, run the comparison, and view structural
stats, textual differences and the AI semantic summary. Clearly separates
deterministic results from AI interpretation.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class DocumentComparisonDialog(QDialog):
    """Compares two documents (structural + textual + semantic)."""

    def __init__(
        self,
        service,
        file_a: str = "",
        file_b: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._file_a = file_a
        self._file_b = file_b
        self.setWindowTitle("Compare Files & Documents")
        self.setMinimumSize(760, 620)
        self.setModal(False)
        self._setup_ui()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        picker = QHBoxLayout()
        self.file_a_label = QLabel(self._file_a or "File A (choose…)")
        self.file_a_label.setWordWrap(True)
        btn_a = QPushButton("File A…")
        btn_a.clicked.connect(lambda: self._pick("a"))
        self.file_b_label = QLabel(self._file_b or "File B (choose…)")
        self.file_b_label.setWordWrap(True)
        btn_b = QPushButton("File B…")
        btn_b.clicked.connect(lambda: self._pick("b"))
        picker.addWidget(self.file_a_label, 3)
        picker.addWidget(btn_a)
        picker.addWidget(QLabel("  vs  "))
        picker.addWidget(self.file_b_label, 3)
        picker.addWidget(btn_b)
        layout.addLayout(picker)

        actions = QHBoxLayout()
        self.compare_btn = QPushButton("🔍 Compare Files")
        self.compare_btn.clicked.connect(self._on_compare)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(self.compare_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.status_label)

        self.output_area = QScrollArea()
        self.output_area.setWidgetResizable(True)
        host = QWidget()
        self.output_layout = QVBoxLayout(host)
        self.output_layout.addStretch(1)
        self.output_area.setWidget(host)
        layout.addWidget(self.output_area, 1)

    def set_files(self, file_a: str, file_b: str, auto_run: bool = True) -> None:
        """Pre-populate File A and File B and optionally trigger comparison."""
        self._file_a = file_a
        self._file_b = file_b
        self.file_a_label.setText(file_a)
        self.file_b_label.setText(file_b)
        if auto_run and file_a and file_b:
            self._on_compare()

    # ------------------------------------------------------------------ #
    def _pick(self, which: str) -> None:
        filter_str = (
            "All Supported Files (*.pdf *.docx *.txt *.md *.py *.csv *.json *.jpg *.jpeg *.png *.webp *.mp3 *.wav *.mp4 *.mkv);;"
            "Documents (*.pdf *.docx *.txt *.md *.py *.csv *.json *.html *.log);;"
            "Images (*.jpg *.jpeg *.png *.webp *.bmp *.gif);;"
            "Audio & Video (*.mp3 *.wav *.flac *.m4a *.mp4 *.mkv *.mov);;"
            "All Files (*)"
        )
        path, _ = QFileDialog.getOpenFileName(
            self, f"Choose File {which.upper()} for Comparison",
            "", filter_str,
        )
        if not path:
            return
        if which == "a":
            self._file_a = path
            self.file_a_label.setText(path)
        else:
            self._file_b = path
            self.file_b_label.setText(path)

    # ------------------------------------------------------------------ #
    def _clear_output(self) -> None:
        while self.output_layout.count() > 1:
            item = self.output_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _add_section(self, title: str, text: str, monospace: bool = False) -> None:
        head = QLabel(f"<b style='font-size: 13px;'>{title}</b>")
        self.output_layout.insertWidget(self.output_layout.count() - 1, head)
        body = QLabel()
        if "###" in text or "•" in text or "<b>" in text:
            body.setTextFormat(Qt.MarkdownText)
        body.setText(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet(
            "padding: 8px; background: #1d1d1d; border-radius: 6px; font-size: 12px; line-height: 1.4;"
            + ("font-family: monospace;" if monospace else "")
        )
        self.output_layout.insertWidget(self.output_layout.count() - 1, body)

    # ------------------------------------------------------------------ #
    def _on_compare(self) -> None:
        if not self._file_a or not self._file_b:
            self.status_label.setText("Choose both documents first.")
            self.status_label.setStyleSheet("color: #e0a030; padding: 4px;")
            return
        if os.path.abspath(self._file_a) == os.path.abspath(self._file_b):
            self.status_label.setText("The two documents are the same file.")
            self.status_label.setStyleSheet("color: #e0a030; padding: 4px;")
            return
        self._clear_output()
        self.status_label.setText("Comparing…")
        self.status_label.setStyleSheet("color: gray; padding: 4px;")
        try:
            result = self._service.compare(self._file_a, self._file_b)
        except Exception as exc:
            self.status_label.setText(f"Comparison failed: {exc}")
            self.status_label.setStyleSheet("color: #c04040; padding: 4px;")
            return

        if result.error:
            self.status_label.setText(result.error)
            self.status_label.setStyleSheet("color: #e0a030; padding: 4px;")
            return

        self.status_label.setText("✓ Comparison complete")
        self.status_label.setStyleSheet("color: green; padding: 4px;")

        sa, sb = result.structural_a, result.structural_b
        self._add_section(
            "Structural",
            f"A: {os.path.basename(self._file_a)}\n"
            f"   format {sa.format} · {sa.word_count} words · "
            f"{sa.char_count} chars · {sa.page_or_section_count} pages/sections"
            + (f"\n   headings: {', '.join(sa.headings[:5])}" if sa.headings else "")
            + f"\n\nB: {os.path.basename(self._file_b)}\n"
            f"   format {sb.format} · {sb.word_count} words · "
            f"{sb.char_count} chars · {sb.page_or_section_count} pages/sections"
            + (f"\n   headings: {', '.join(sb.headings[:5])}" if sb.headings else ""),
            monospace=True,
        )

        td = result.textual
        self._add_section(
            "Textual differences",
            f"Common ratio: {td.unchanged_ratio:.2f}\n"
            f"Added: {td.added_chars} chars · Removed: {td.removed_chars} chars"
            + ("\n\nADDED LINES:\n" + "\n".join(td.added_lines) if td.added_lines else "")
            + ("\n\nREMOVED LINES:\n" + "\n".join(td.removed_lines) if td.removed_lines else ""),
            monospace=True,
        )

        self._add_section(
            "AI interpretation (grounded in the diff)",
            result.semantic_summary or "(LLM unavailable — deterministic results above.)",
        )
