"""Document Comparison dialog — B7-5 (#21).

Entry: Tools → Compare Documents.

Pick Document A and Document B, run the comparison asynchronously in a background
thread, and view structural stats, textual differences, deterministic numerical
audits, and AI semantic interpretations. Provides side-by-side visual diffs
and exportable HTML / Markdown comparison reports.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from services.document_comparison_service import get_file_type_info


class CompareWorker(QThread):
    """Background worker thread to run document comparison without freezing UI."""

    finished = Signal(object)
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, service, file_a: str, file_b: str, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._file_a = file_a
        self._file_b = file_b

    def run(self) -> None:
        try:
            self.progress.emit("Extracting content and analyzing differences…")
            result = self._service.compare(self._file_a, self._file_b)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class DocumentComparisonDialog(QDialog):
    """Compares two documents (structural + textual + audit + semantic)."""

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
        self._worker: Optional[CompareWorker] = None
        self._last_result = None

        self.setWindowTitle("Compare Files & Documents")
        self.setMinimumSize(850, 680)
        self.setModal(False)
        self._setup_ui()

    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # File Selectors Bar
        picker_frame = QFrame()
        picker_frame.setStyleSheet(
            "QFrame { background: #1f232a; border-radius: 8px; padding: 6px; }"
        )
        picker_layout = QHBoxLayout(picker_frame)
        picker_layout.setContentsMargins(8, 6, 8, 6)

        # File A
        self.file_a_label = QLabel(self._file_a or "File A (choose…)")
        self.file_a_label.setWordWrap(True)
        self.file_a_label.setStyleSheet("color: #cfd8dc; font-weight: 500;")
        btn_a = QPushButton("File A…")
        btn_a.setCursor(Qt.PointingHandCursor)
        btn_a.clicked.connect(lambda: self._pick("a"))

        # VS divider
        vs_lbl = QLabel(" VS ")
        vs_lbl.setStyleSheet("font-weight: bold; color: #4fc3f7; padding: 0 6px;")

        # File B
        self.file_b_label = QLabel(self._file_b or "File B (choose…)")
        self.file_b_label.setWordWrap(True)
        self.file_b_label.setStyleSheet("color: #cfd8dc; font-weight: 500;")
        btn_b = QPushButton("File B…")
        btn_b.setCursor(Qt.PointingHandCursor)
        btn_b.clicked.connect(lambda: self._pick("b"))

        picker_layout.addWidget(self.file_a_label, 3)
        picker_layout.addWidget(btn_a)
        picker_layout.addWidget(vs_lbl)
        picker_layout.addWidget(self.file_b_label, 3)
        picker_layout.addWidget(btn_b)
        layout.addWidget(picker_frame)

        # Actions Bar
        actions = QHBoxLayout()
        self.compare_btn = QPushButton("🔍 Compare Files")
        self.compare_btn.setCursor(Qt.PointingHandCursor)
        self.compare_btn.setStyleSheet(
            "QPushButton { background: #1976d2; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px; }"
            "QPushButton:hover { background: #2196f3; }"
            "QPushButton:disabled { background: #37474f; color: #78909c; }"
        )
        self.compare_btn.clicked.connect(self._on_compare)

        self.cancel_btn = QPushButton("⏹ Cancel")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._on_cancel)

        self.export_btn = QPushButton("💾 Export Report…")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._on_export)

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)

        actions.addWidget(self.compare_btn)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.export_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        # Progress and Status
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 2px 4px; color: #90a4ae; font-size: 11px;")
        layout.addWidget(self.status_label)

        # Tabs Layout
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #37474f; border-radius: 4px; }"
            "QTabBar::tab { padding: 7px 14px; font-weight: 500; }"
            "QTabBar::tab:selected { color: #4fc3f7; font-weight: bold; border-bottom: 2px solid #4fc3f7; }"
        )

        # Tab 1: Summary & Findings
        self.tab_summary = QWidget()
        self._setup_summary_tab()
        self.tab_widget.addTab(self.tab_summary, "📊 Summary & Insights")

        # Tab 2: Side-by-Side Diff
        self.tab_diff = QWidget()
        self._setup_diff_tab()
        self.tab_widget.addTab(self.tab_diff, "⚖️ Side-by-Side Diff")

        # Tab 3: Structural Metrics
        self.tab_metrics = QWidget()
        self._setup_metrics_tab()
        self.tab_widget.addTab(self.tab_metrics, "📐 Structural Metrics")

        # Tab 4: Visual Preview
        self.tab_preview = QWidget()
        self._setup_preview_tab()
        self.tab_widget.addTab(self.tab_preview, "🖼️ Visual Preview")

        layout.addWidget(self.tab_widget, 1)

    # ------------------------------------------------------------------ #
    # TAB 1: SUMMARY & INSIGHTS
    # ------------------------------------------------------------------ #
    def _setup_summary_tab(self) -> None:
        vbox = QVBoxLayout(self.tab_summary)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Verdict Header Card
        self.verdict_card = QLabel("Select two documents and click 'Compare Files' to begin.")
        self.verdict_card.setWordWrap(True)
        self.verdict_card.setStyleSheet(
            "background: #1e2229; border: 1px solid #2d323c; border-radius: 6px; padding: 10px; font-size: 13px;"
        )
        vbox.addWidget(self.verdict_card)

        # Semantic Findings (AI interpretation)
        lbl_insights = QLabel("<b>🧠 Content Analysis & Semantic Findings:</b>")
        lbl_insights.setStyleSheet("color: #eceff1;")
        vbox.addWidget(lbl_insights)

        self.semantic_browser = QTextBrowser()
        self.semantic_browser.setOpenExternalLinks(True)
        self.semantic_browser.setStyleSheet(
            "background: #14171c; border: 1px solid #2d323c; border-radius: 6px; padding: 8px; color: #eceff1; line-height: 1.4;"
        )
        vbox.addWidget(self.semantic_browser, 2)

        # Numerical & Entity Audit Table
        lbl_audit = QLabel("<b>🔢 Numerical & Entity Audit (Deterministic Ground Truth):</b>")
        lbl_audit.setStyleSheet("color: #eceff1;")
        vbox.addWidget(lbl_audit)

        self.audit_table = QTableWidget(0, 4)
        self.audit_table.setHorizontalHeaderLabels(["Category", "File A Value", "File B Value", "Difference Status"])
        self.audit_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.audit_table.setStyleSheet(
            "QTableWidget { background: #14171c; border: 1px solid #2d323c; gridline-color: #262c36; color: #e0e0e0; }"
            "QHeaderView::section { background: #1f242d; color: #90a4ae; font-weight: bold; border: 1px solid #2d323c; padding: 4px; }"
        )
        self.audit_table.setSelectionBehavior(QTableWidget.SelectRows)
        vbox.addWidget(self.audit_table, 2)

    # ------------------------------------------------------------------ #
    # TAB 2: SIDE-BY-SIDE DIFF
    # ------------------------------------------------------------------ #
    def _setup_diff_tab(self) -> None:
        vbox = QVBoxLayout(self.tab_diff)
        vbox.setContentsMargins(8, 8, 8, 8)
        self.diff_browser = QTextBrowser()
        self.diff_browser.setStyleSheet(
            "background: #0d1117; border: 1px solid #30363d; border-radius: 6px;"
        )
        vbox.addWidget(self.diff_browser)

    # ------------------------------------------------------------------ #
    # TAB 3: STRUCTURAL METRICS
    # ------------------------------------------------------------------ #
    def _setup_metrics_tab(self) -> None:
        vbox = QVBoxLayout(self.tab_metrics)
        vbox.setContentsMargins(8, 8, 8, 8)
        self.metrics_table = QTableWidget(0, 3)
        self.metrics_table.setHorizontalHeaderLabels(["Metric / Property", "File A", "File B"])
        self.metrics_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.metrics_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.metrics_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.metrics_table.setStyleSheet(
            "QTableWidget { background: #14171c; border: 1px solid #2d323c; gridline-color: #262c36; color: #e0e0e0; }"
            "QHeaderView::section { background: #1f242d; color: #90a4ae; font-weight: bold; border: 1px solid #2d323c; padding: 4px; }"
        )
        vbox.addWidget(self.metrics_table)

    # ------------------------------------------------------------------ #
    # TAB 4: VISUAL PREVIEW
    # ------------------------------------------------------------------ #
    def _setup_preview_tab(self) -> None:
        vbox = QVBoxLayout(self.tab_preview)
        vbox.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Horizontal)

        # Preview A
        panel_a = QWidget()
        lay_a = QVBoxLayout(panel_a)
        lay_a.addWidget(QLabel("<b>File A Preview:</b>"))
        self.img_lbl_a = QLabel("No preview available")
        self.img_lbl_a.setAlignment(Qt.AlignCenter)
        self.img_lbl_a.setStyleSheet("background: #14171c; border: 1px solid #2d323c; border-radius: 6px; padding: 12px;")
        lay_a.addWidget(self.img_lbl_a, 1)
        splitter.addWidget(panel_a)

        # Preview B
        panel_b = QWidget()
        lay_b = QVBoxLayout(panel_b)
        lay_b.addWidget(QLabel("<b>File B Preview:</b>"))
        self.img_lbl_b = QLabel("No preview available")
        self.img_lbl_b.setAlignment(Qt.AlignCenter)
        self.img_lbl_b.setStyleSheet("background: #14171c; border: 1px solid #2d323c; border-radius: 6px; padding: 12px;")
        lay_b.addWidget(self.img_lbl_b, 1)
        splitter.addWidget(panel_b)

        vbox.addWidget(splitter)

    # ------------------------------------------------------------------ #
    def _update_file_label(self, which: str) -> None:
        path = self._file_a if which == "a" else self._file_b
        lbl = self.file_a_label if which == "a" else self.file_b_label
        if path:
            _, type_name = get_file_type_info(path)
            fn = os.path.basename(path)
            lbl.setText(f"{fn}  [{type_name}]")
            lbl.setToolTip(path)
        else:
            lbl.setText(f"File {which.upper()} (choose…)")
            lbl.setToolTip("")

    def set_files(self, file_a: str, file_b: str, auto_run: bool = True) -> None:
        """Pre-populate File A and File B and optionally trigger comparison."""
        self._file_a = file_a
        self._file_b = file_b
        self._update_file_label("a")
        self._update_file_label("b")
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
            self._update_file_label("a")
        else:
            self._file_b = path
            self._update_file_label("b")

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

        # Start asynchronous worker
        self.status_label.setText("Comparing documents… (analyzing content & extracting diffs)")
        self.status_label.setStyleSheet("color: #4fc3f7; padding: 4px;")
        self.progress_bar.setVisible(True)
        self.compare_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.export_btn.setEnabled(False)

        self._worker = CompareWorker(self._service, self._file_a, self._file_b, self)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.finished.connect(self._on_compare_finished)
        self._worker.error.connect(self._on_compare_error)
        self._worker.start()

    def _on_worker_progress(self, msg: str) -> None:
        self.status_label.setText(msg)

    def _on_compare_error(self, err: str) -> None:
        self.progress_bar.setVisible(False)
        self.compare_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.status_label.setText(f"Comparison failed: {err}")
        self.status_label.setStyleSheet("color: #f44336; padding: 4px;")

    def _on_cancel(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
        self.progress_bar.setVisible(False)
        self.compare_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.status_label.setText("Comparison cancelled.")
        self.status_label.setStyleSheet("color: #e0a030; padding: 4px;")

    def _on_compare_finished(self, result) -> None:
        self.progress_bar.setVisible(False)
        self.compare_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self._last_result = result

        if result.error:
            self.status_label.setText(result.error)
            self.status_label.setStyleSheet("color: #e0a030; padding: 4px;")
            return

        self.status_label.setText("✓ Comparison complete")
        self.status_label.setStyleSheet("color: #4caf50; padding: 4px;")
        self.export_btn.setEnabled(True)

        self._render_results(result)

    # ------------------------------------------------------------------ #
    def _render_results(self, result) -> None:
        # 1. Tab 1: Verdict & AI Summary
        sim_pct = round((result.textual.unchanged_ratio if result.textual else 0) * 100, 1)
        fn_a = os.path.basename(self._file_a)
        fn_b = os.path.basename(self._file_b)
        cat_a, type_a = get_file_type_info(self._file_a)
        cat_b, type_b = get_file_type_info(self._file_b)

        verdict_color = "#4caf50" if sim_pct >= 90 else ("#ff9800" if sim_pct >= 40 else "#f44336")
        self.verdict_card.setText(
            f"<div style='font-size: 14px; font-weight: bold;'>"
            f"Comparing: <span style='color: #4fc3f7;'>{fn_a}</span> <span style='font-size: 11px; color: #90a4ae;'>({type_a})</span>"
            f" &nbsp;vs&nbsp; "
            f"<span style='color: #4fc3f7;'>{fn_b}</span> <span style='font-size: 11px; color: #90a4ae;'>({type_b})</span></div>"
            f"<div style='margin-top: 6px; font-size: 13px;'>"
            f"Overall Similarity: <b style='color: {verdict_color};'>{sim_pct}% Match</b>"
            f"</div>"
        )

        # Semantic summary markdown
        if result.semantic_summary:
            self.semantic_browser.setMarkdown(result.semantic_summary)
        else:
            self.semantic_browser.setText("(LLM unavailable — deterministic results shown below.)")

        # Numerical & Entity Audit Table
        self.audit_table.setRowCount(0)
        audit_items = getattr(result, "numerical_audit", [])
        if audit_items:
            self.audit_table.setRowCount(len(audit_items))
            for row_idx, item in enumerate(audit_items):
                cat_item = QTableWidgetItem(str(item.get("category", "")))
                fa_item = QTableWidgetItem(str(item.get("file_a", "")))
                fb_item = QTableWidgetItem(str(item.get("file_b", "")))
                st_text = str(item.get("status", ""))
                st_item = QTableWidgetItem(st_text)

                if st_text == "Identical":
                    st_item.setForeground(QColor("#4caf50"))
                elif st_text == "Changed":
                    st_item.setForeground(QColor("#ff9800"))
                elif "Only in A" in st_text:
                    st_item.setForeground(QColor("#42a5f5"))
                else:
                    st_item.setForeground(QColor("#ab47bc"))

                self.audit_table.setItem(row_idx, 0, cat_item)
                self.audit_table.setItem(row_idx, 1, fa_item)
                self.audit_table.setItem(row_idx, 2, fb_item)
                self.audit_table.setItem(row_idx, 3, st_item)
        else:
            self.audit_table.setRowCount(1)
            msg_item = QTableWidgetItem("No distinct numbers, currencies, dates, or IDs detected.")
            self.audit_table.setItem(0, 0, msg_item)

        # 2. Tab 2: Side-by-Side Diff Browser
        diff_html = getattr(result, "side_by_side_html", "")
        if diff_html:
            self.diff_browser.setHtml(diff_html)
        else:
            self.diff_browser.setText("No textual diff available.")

        # 3. Tab 3: Structural Metrics Table
        sa = result.structural_a
        sb = result.structural_b
        td = result.textual

        def _fmt_size(b: int) -> str:
            if b < 1024:
                return f"{b} B"
            if b < 1024 * 1024:
                return f"{b / 1024:.1f} KB"
            return f"{b / (1024 * 1024):.2f} MB"

        def _fmt_pages(s, cat, file_p):
            if not s:
                return "0"
            ext = os.path.splitext(file_p)[1].lower()
            if cat == "Image":
                return "1 (Single Image Frame)"
            elif cat in ("Audio", "Video"):
                return "1 (Media Stream)"
            elif ext == ".pdf":
                return f"{s.page_or_section_count} Pages"
            return f"{s.page_or_section_count} Sections"

        def _fmt_headings(s, cat):
            if not s:
                return "None"
            if cat == "Image":
                return "N/A (Visual Image Content)"
            return ", ".join(s.headings[:5]) if s.headings else "None detected"

        metrics_data = [
            ("Format / Media Type", f"{sa.format if sa else ''} ({type_a})", f"{sb.format if sb else ''} ({type_b})"),
            ("File Size", _fmt_size(sa.file_size_bytes if sa else 0), _fmt_size(sb.file_size_bytes if sb else 0)),
            ("Extracted Word Count", str(sa.word_count if sa else 0), str(sb.word_count if sb else 0)),
            ("Character Count", str(sa.char_count if sa else 0), str(sb.char_count if sb else 0)),
            ("Pages / Sections", _fmt_pages(sa, cat_a, self._file_a), _fmt_pages(sb, cat_b, self._file_b)),
            ("Detected Headings", _fmt_headings(sa, cat_a), _fmt_headings(sb, cat_b)),
            ("Text Similarity", f"{sim_pct}%", f"{sim_pct}%"),
            ("Added Characters", "-", str(td.added_chars if td else 0)),
            ("Removed Characters", str(td.removed_chars if td else 0), "-"),
        ]

        self.metrics_table.setRowCount(len(metrics_data))
        for row_idx, (lbl, val_a, val_b) in enumerate(metrics_data):
            self.metrics_table.setItem(row_idx, 0, QTableWidgetItem(lbl))
            self.metrics_table.setItem(row_idx, 1, QTableWidgetItem(val_a))
            self.metrics_table.setItem(row_idx, 2, QTableWidgetItem(val_b))

        # 4. Tab 4: Visual Preview
        self._update_preview(self._file_a, self.img_lbl_a)
        self._update_preview(self._file_b, self.img_lbl_b)

    def _update_preview(self, file_path: str, label: QLabel) -> None:
        if not file_path or not os.path.isfile(file_path):
            label.setText("No file selected")
            return
        ext = os.path.splitext(file_path)[1].lower()
        if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                label.setPixmap(pixmap.scaled(380, 380, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        elif ext == ".pdf":
            try:
                import fitz
                doc = fitz.open(file_path)
                if len(doc) > 0:
                    page = doc[0]
                    pix = page.get_pixmap(dpi=120)
                    img_bytes = pix.tobytes("png")
                    pixmap = QPixmap()
                    if pixmap.loadFromData(img_bytes):
                        label.setPixmap(pixmap.scaled(380, 380, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                        return
            except Exception:
                pass
        label.setText(f"File preview not applicable for format '{ext}'")

    # ------------------------------------------------------------------ #
    def _on_export(self) -> None:
        if not self._last_result:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Comparison Report",
            "comparison_report.html",
            "HTML Report (*.html);;Markdown Report (*.md)",
        )
        if not path:
            return

        success = self._service.export_report(self._last_result, path)
        if success:
            QMessageBox.information(self, "Export Successful", f"Comparison report saved successfully to:\n{path}")
        else:
            QMessageBox.warning(self, "Export Failed", "Could not export comparison report. Check permissions or disk space.")

    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
        super().closeEvent(event)
