"""Multi-file Rename Selection and Preview dialog.

Allows the user to select files in a directory, triggers the AI rename suggestion
generation with a progress bar, and lets the user preview and approve renames in-place.
"""

from __future__ import annotations

import os
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QStackedWidget,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)


class MultiRenameSelectionDialog(QDialog):
    """Unified wizard for selecting, analyzing, previewing, and approving file renames."""

    def __init__(self, folder_path: str, container=None, parent=None) -> None:
        super().__init__(parent)
        self.folder_path = os.path.abspath(folder_path)
        self.container = container
        self.selected_paths: List[str] = []
        self._suggestions: List = []
        self._task_id: str | None = None

        self.setWindowTitle("AI Multi-File Renaming")
        self.resize(750, 500)
        self._setup_ui()
        self._populate_files()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Page 0: File Selection
        self.selection_page = QWidget()
        self._setup_selection_page()
        self.stack.addWidget(self.selection_page)

        # Page 1: Progress Loader
        self.progress_page = QWidget()
        self._setup_progress_page()
        self.stack.addWidget(self.progress_page)

        # Page 2: Preview & Approval
        self.preview_page = QWidget()
        self._setup_preview_page()
        self.stack.addWidget(self.preview_page)

        self.stack.setCurrentIndex(0)

    # ------------------------------------------------------------------ #
    # Page Setup Methods
    # ------------------------------------------------------------------ #
    def _setup_selection_page(self) -> None:
        layout = QVBoxLayout(self.selection_page)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel("Select the files you wish to rename based on their content:")
        label.setWordWrap(True)
        layout.addWidget(label)

        # Filter bar
        filter_layout = QHBoxLayout()
        filter_label = QLabel("Filter:")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Search file names...")
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_edit)
        layout.addLayout(filter_layout)

        # List of files
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        # Quick select buttons
        select_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all)
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self._deselect_all)
        select_layout.addWidget(select_all_btn)
        select_layout.addWidget(deselect_all_btn)
        select_layout.addStretch(1)
        layout.addLayout(select_layout)

        # Actions buttons
        actions = QHBoxLayout()
        self.proceed_btn = QPushButton("Proceed")
        self.proceed_btn.setDefault(True)
        self.proceed_btn.clicked.connect(self._start_analysis)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(self.proceed_btn)
        actions.addStretch(1)
        actions.addWidget(cancel_btn)
        layout.addLayout(actions)

    def _setup_progress_page(self) -> None:
        layout = QVBoxLayout(self.progress_page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addStretch(1)

        self.progress_title = QLabel("AI Analysis in Progress...")
        self.progress_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.progress_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.progress_title)

        self.progress_detail = QLabel("Preparing to analyze files...")
        self.progress_detail.setAlignment(Qt.AlignCenter)
        self.progress_detail.setWordWrap(True)
        layout.addWidget(self.progress_detail)

        layout.addSpacing(10)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        layout.addStretch(1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        abort_btn = QPushButton("Cancel / Abort")
        abort_btn.clicked.connect(self._cancel_analysis)
        actions.addWidget(abort_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

    def _setup_preview_page(self) -> None:
        layout = QVBoxLayout(self.preview_page)
        layout.setContentsMargins(0, 0, 0, 0)

        note = QLabel(
            "Proposed names are derived from AI analysis of each file's content. "
            "Nothing is renamed until you approve. Extension changes are never allowed."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; padding: 2px;")
        layout.addWidget(note)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Current Name", "Proposed Name", "Status"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.approve_selected_btn = QPushButton("Approve Selected")
        self.approve_selected_btn.clicked.connect(self._approve_selected)
        self.approve_all_btn = QPushButton("Approve All")
        self.approve_all_btn.clicked.connect(self._approve_all)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(self.approve_selected_btn)
        actions.addWidget(self.approve_all_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    # ------------------------------------------------------------------ #
    # File Selection Logic
    # ------------------------------------------------------------------ #
    def _populate_files(self) -> None:
        if not os.path.isdir(self.folder_path):
            return

        try:
            files = sorted(
                [
                    f for f in os.listdir(self.folder_path)
                    if os.path.isfile(os.path.join(self.folder_path, f))
                ],
                key=lambda s: s.lower()
            )
        except Exception:
            files = []

        for filename in files:
            full_path = os.path.join(self.folder_path, filename)
            item = QListWidgetItem(filename)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, full_path)
            self.list_widget.addItem(item)

    def _select_all(self) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Checked)

    def _deselect_all(self) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Unchecked)

    def _on_filter_changed(self, text: str) -> None:
        query = text.lower().strip()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(query not in item.text().lower())

    # ------------------------------------------------------------------ #
    # Progress & AI Analysis Tasks
    # ------------------------------------------------------------------ #
    def _start_analysis(self) -> None:
        self.selected_paths = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                path = item.data(Qt.UserRole)
                if path:
                    self.selected_paths.append(path)

        if not self.selected_paths:
            return

        # Transition to Progress Page
        self.stack.setCurrentIndex(1)
        self.progress_bar.setRange(0, len(self.selected_paths))
        self.progress_bar.setValue(0)
        self.progress_detail.setText(f"Starting analysis of {len(self.selected_paths)} file(s)...")

        # Submit background task
        def _do(progress_callback, cancel_event, fps):
            from concurrent.futures import ThreadPoolExecutor, as_completed
            service = self.container.rename_suggestion_service
            suggestions = [None] * len(fps)
            max_workers = min(8, len(fps))
            completed = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_idx = {
                    executor.submit(service.suggest_from_content, fp): i
                    for i, fp in enumerate(fps)
                }
                for future in as_completed(future_to_idx):
                    if cancel_event and cancel_event.is_set():
                        for f in future_to_idx:
                            f.cancel()
                        break
                    idx = future_to_idx[future]
                    try:
                        sug = future.result()
                        if sug:
                            suggestions[idx] = sug
                    except Exception:
                        pass
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(fps))
            return [s for s in suggestions if s is not None]

        self._task_id = self.container.tasks.submit(
            _do, "ai_rename_suggestions", None, self.selected_paths,
            on_finished=self._on_analysis_finished,
            on_error=self._on_analysis_error,
            on_progress=self._on_analysis_progress,
        )

    def _on_analysis_progress(self, current: int, total: int) -> None:
        self.progress_bar.setValue(current)
        if current < total:
            current_path = self.selected_paths[current]
            self.progress_detail.setText(
                f"Analyzing ({current + 1}/{total}): {os.path.basename(current_path)}"
            )
        else:
            self.progress_detail.setText("Completing analysis...")

    def _on_analysis_finished(self, suggestions) -> None:
        self._task_id = None
        self._suggestions = suggestions or []
        # Transition to Preview Page
        self.stack.setCurrentIndex(2)
        self._populate_preview()

    def _on_analysis_error(self, exc) -> None:
        self._task_id = None
        self.stack.setCurrentIndex(0)
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "AI Rename Failed", f"An error occurred during AI analysis:\n{exc}")

    def _cancel_analysis(self) -> None:
        if self._task_id:
            self.container.tasks.cancel(self._task_id)
            self._task_id = None
        self.stack.setCurrentIndex(0)

    # ------------------------------------------------------------------ #
    # Preview & Approval Implementation
    # ------------------------------------------------------------------ #
    def _populate_preview(self) -> None:
        self.table.setRowCount(len(self._suggestions))
        for row, sug in enumerate(self._suggestions):
            self.table.setItem(row, 0, QTableWidgetItem(sug.current_name))
            self.table.setItem(row, 1, QTableWidgetItem(sug.proposed_name))
            if sug.errors:
                item = QTableWidgetItem("⚠ " + "; ".join(sug.errors[:2]))
                item.setForeground(Qt.red)
            else:
                item = QTableWidgetItem("ready")
                item.setForeground(Qt.green)
            self.table.setItem(row, 2, item)
            self.table.setRowHeight(row, 22)

    def _approve_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            self.status_label.setText("Select at least one row to approve.")
            self.status_label.setStyleSheet("color: #e0a030;")
            return
        self._run_approve([self._suggestions[r] for r in sorted(rows)])

    def _approve_all(self) -> None:
        self._run_approve(list(self._suggestions))

    def _run_approve(self, suggestions: List) -> None:
        from services.file_mover import rename_file, MoveError
        done = 0
        failed = []
        for sug in suggestions:
            if sug.errors and sug.errors != ["Already renamed"]:
                failed.append(f"{sug.current_name}: {sug.errors[0]}")
                continue
            if sug.errors == ["Already renamed"]:
                continue
            try:
                result = rename_file(
                    src=sug.file_path,
                    new_name=sug.proposed_name,
                    session_factory=self.container.db.session,
                    retrieval=self.container.retrieval_engine,
                    vector_engine=self.container.vector_engine,
                )
                if result.ok:
                    done += 1
                    parent = self.parent()
                    if parent and hasattr(parent, "bus"):
                        parent.bus.rename_completed.emit(result.destination)
                        parent.bus.relationships_updated.emit()
                        if hasattr(parent, "docks") and hasattr(parent.docks, "indexed_files_widget"):
                            parent.docks.indexed_files_widget.refresh_data()
                        parent.bus.files_changed.emit(os.path.dirname(result.destination))
                    
                    sug.current_name = sug.proposed_name
                    sug.file_path = result.destination
                    sug.errors = ["Already renamed"]
                else:
                    failed.append(f"{sug.current_name}: {result.error if hasattr(result, 'error') else 'failed'}")
            except MoveError as exc:
                failed.append(f"{sug.current_name}: {exc}")
            except Exception as exc:
                failed.append(f"{sug.current_name}: {exc}")

        if failed:
            self.status_label.setText(
                f"Renamed {done} file(s). Failures: " + "; ".join(failed[:3])
            )
            self.status_label.setStyleSheet("color: #c07030;")
        else:
            self.status_label.setText(f"✓ Renamed {done} file(s).")
            self.status_label.setStyleSheet("color: green;")
        self._populate_preview()

    def get_selected_files(self) -> List[str]:
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                path = item.data(Qt.UserRole)
                if path:
                    selected.append(path)
        return selected

    def closeEvent(self, event) -> None:
        self._cancel_analysis()
        super().closeEvent(event)
