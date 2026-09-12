"""Content-Based File Organization Dialog — Single-Action Intelligent Clustering.

Automatically groups workspace files by content relationships (>= threshold similarity)
into descriptive folders named after the relation/core content of the files.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.file_organizer_service import (
    FileOrganizerService,
    MoveResult,
    OrganizationCandidate,
    ProposedFolderCluster,
)

logger = logging.getLogger(__name__)


class OrganizeWorkerThread(QThread):
    """Background worker thread for content analysis and file organization."""

    progress = Signal(int, int, str)
    completed = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        organizer: FileOrganizerService,
        source_dir: str,
        dest_dir: str,
        threshold: int,
        only_groups: bool,
        retrieval_engine=None,
    ) -> None:
        super().__init__()
        self.organizer = organizer
        self.source_dir = source_dir
        self.dest_dir = dest_dir
        self.threshold = threshold
        self.only_groups = only_groups
        self.retrieval_engine = retrieval_engine
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            self.progress.emit(10, 100, "Scanning files and analyzing multi-modal content similarity…")
            if self.cancel_event.is_set():
                return

            # Step 1: Detect content relationships & build clusters using FAISS embeddings
            clusters = self.organizer.auto_cluster_folder(
                folder_path=self.source_dir,
                min_similarity=self.threshold,
                only_relation_clusters=self.only_groups,
                retrieval_engine=self.retrieval_engine,
            )

            if self.cancel_event.is_set():
                return

            selected_clusters = [c for c in clusters if c.selected and c.files]
            if not selected_clusters:
                self.completed.emit({
                    "ok": True,
                    "folder_count": 0,
                    "moved_count": 0,
                    "failed_count": 0,
                    "clusters": [],
                    "message": "No related file groups found matching the similarity threshold.",
                })
                return

            self.progress.emit(
                35, 100, f"Detected {len(selected_clusters)} group(s). Creating folders and moving files…"
            )

            # Step 2: Execute moves with progress callbacks
            def _move_progress(current: int, total: int, msg: str):
                pct = int(35 + (current / max(total, 1)) * 60)
                self.progress.emit(pct, 100, msg)

            result = self.organizer.execute_auto_clustering(
                clusters=selected_clusters,
                destination_parent_dir=self.dest_dir,
                progress_callback=_move_progress,
                cancel_flag=self.cancel_event,
            )

            result["clusters"] = selected_clusters
            self.progress.emit(100, 100, "Organization complete!")
            self.completed.emit(result)

        except Exception as exc:
            logger.exception("Error during folder organization: %s", exc)
            self.error.emit(str(exc))


class OrganizeDialog(QDialog):
    """Intelligent Content-Based File Organization Dialog."""

    organization_completed = Signal(dict)

    def __init__(
        self,
        organizer_service: FileOrganizerService,
        current_dir: str = "",
        open_file_callback: Optional[Callable[[str], None]] = None,
        retrieval_engine=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._organizer = organizer_service
        self._retrieval_engine = retrieval_engine
        self._current_dir = os.path.abspath(current_dir) if current_dir else os.path.expanduser("~")
        self._open_file_callback = open_file_callback
        self._worker: Optional[OrganizeWorkerThread] = None
        self._last_result: Optional[dict] = None

        # Backward-compatibility attribute for legacy callers
        self.folder_name_edit = QLineEdit("Organized Files")

        self.setWindowTitle("Organize Files into Folders")
        self.setMinimumSize(880, 560)
        self.setModal(False)
        self._setup_ui()


    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header description
        title_label = QLabel("📁 Organize Files into Folders")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #1e293b;")
        layout.addWidget(title_label)

        desc_label = QLabel(
            "Detects relationships based on file content (text, documents, and images) "
            "and organizes related files into new folders named after their shared relationship."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #475569; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(desc_label)

        # ----------------- Step 1: Folder Selection -----------------
        folder_group = QGroupBox("Folder Configuration")
        folder_layout = QVBoxLayout(folder_group)

        # Source Folder
        src_row = QHBoxLayout()
        src_lbl = QLabel("Source Folder:")
        src_lbl.setFixedWidth(140)
        self.source_edit = QLineEdit(self._current_dir)
        self.source_edit.setToolTip("The folder containing files to be organized")
        src_browse_btn = QPushButton("Browse…")
        src_browse_btn.clicked.connect(self._browse_source)
        src_row.addWidget(src_lbl)
        src_row.addWidget(self.source_edit, 1)
        src_row.addWidget(src_browse_btn)
        folder_layout.addLayout(src_row)

        # Destination Folder
        dest_row = QHBoxLayout()
        dest_lbl = QLabel("Destination Folder:")
        dest_lbl.setFixedWidth(140)
        self.dest_edit = QLineEdit(self._current_dir)
        self.dest_edit.setToolTip("The folder where organized group folders will be created")
        dest_browse_btn = QPushButton("Browse…")
        dest_browse_btn.clicked.connect(self._browse_destination)
        dest_row.addWidget(dest_lbl)
        dest_row.addWidget(self.dest_edit, 1)
        dest_row.addWidget(dest_browse_btn)
        folder_layout.addLayout(dest_row)

        layout.addWidget(folder_group)

        # ----------------- Step 2: Options -----------------
        options_group = QGroupBox("Organization Options")
        options_layout = QHBoxLayout(options_group)

        thresh_lbl = QLabel("Relationship Threshold:")
        thresh_lbl.setFixedWidth(150)
        self.threshold_combo = QComboBox()
        self.threshold_combo.addItem("Balanced (50% Content Overlap — Recommended)", 50)
        self.threshold_combo.addItem("Broad (40% Content Overlap — Connects more files)", 40)
        self.threshold_combo.addItem("Loose (30% Content Overlap — Catches semantic near-matches)", 30)
        self.threshold_combo.addItem("Strict (60% Content Overlap — Close matches only)", 60)
        options_layout.addWidget(thresh_lbl)
        options_layout.addWidget(self.threshold_combo, 1)

        self.only_groups_check = QCheckBox("Organize related groups only (keeps single files in place)")
        self.only_groups_check.setChecked(False)  # Default OFF — every file gets organized into a folder
        self.only_groups_check.setToolTip(
            "When unchecked (default), ALL files are placed into folders — "
            "related files share a folder, unrelated files each get their own dedicated folder.\n"
            "When checked, only groups with 2+ related files are moved; single files stay in place."
        )
        options_layout.addWidget(self.only_groups_check)

        layout.addWidget(options_group)

        # ----------------- Step 3: Progress & Action Button -----------------
        action_layout = QHBoxLayout()

        self.start_btn = QPushButton("📁 Start Organizing Files")
        self.start_btn.setMinimumHeight(42)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 24px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton:pressed {
                background-color: #1e40af;
            }
            QPushButton:disabled {
                background-color: #94a3b8;
                color: #f1f5f9;
            }
        """)
        self.start_btn.clicked.connect(self._on_start_organization)
        action_layout.addWidget(self.start_btn, 2)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(42)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: white;
                font-weight: bold;
                padding: 8px 18px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #dc2626;
            }
        """)
        self.cancel_btn.clicked.connect(self._on_cancel)
        action_layout.addWidget(self.cancel_btn, 0)

        layout.addLayout(action_layout)

        # Progress bar & Status
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #2563eb;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #475569; font-weight: 500;")
        layout.addWidget(self.status_label)

        # ----------------- Results Table -----------------
        results_group = QGroupBox("Organized Groups & Moved Files")
        results_layout = QVBoxLayout(results_group)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "Group / Folder Name", "Relationship %", "File Count", "Files in Group"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 260)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        results_layout.addWidget(self.table)

        layout.addWidget(results_group, 1)

        # Bottom Bar
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch(1)

        close_btn = QPushButton("Close")
        close_btn.setMinimumWidth(90)
        close_btn.clicked.connect(self.accept)
        bottom_bar.addWidget(close_btn)

        layout.addLayout(bottom_bar)

    # ------------------------------------------------------------------ #
    # Path Browsing & Validation
    # ------------------------------------------------------------------ #
    def _browse_source(self) -> None:
        init_dir = self.source_edit.text().strip() or self._current_dir
        path = QFileDialog.getExistingDirectory(self, "Select Source Folder to Organize", init_dir)
        if path:
            prev_src = self.source_edit.text().strip()
            self.source_edit.setText(path)
            # If destination was pointing to previous source, update it too
            if self.dest_edit.text().strip() == prev_src:
                self.dest_edit.setText(path)

    def _browse_destination(self) -> None:
        init_dir = self.dest_edit.text().strip() or self.source_edit.text().strip() or self._current_dir
        path = QFileDialog.getExistingDirectory(self, "Select Destination Folder for Groups", init_dir)
        if path:
            self.dest_edit.setText(path)

    def _validate_inputs(self) -> Tuple[bool, str]:
        src = self.source_edit.text().strip()
        dst = self.dest_edit.text().strip()

        if not src:
            return False, "Please specify a Source Folder containing the files to organize."
        if not os.path.exists(src):
            return False, f"Source folder does not exist:\n{src}"
        if not os.path.isdir(src):
            return False, f"Source path is not a directory:\n{src}"

        # Check if source has files
        try:
            has_files = any(os.path.isfile(os.path.join(src, f)) for f in os.listdir(src) if not f.startswith('.'))
            if not has_files:
                return False, f"No files found in source folder:\n{src}\nPlease select a folder that contains files to organize."
        except Exception as exc:
            return False, f"Cannot access source folder: {exc}"

        if not dst:
            return False, "Please specify a Destination Folder where group folders will be created."

        # If destination doesn't exist, try creating it
        if not os.path.exists(dst):
            try:
                os.makedirs(dst, exist_ok=True)
            except Exception as exc:
                return False, f"Cannot create destination folder:\n{dst}\nError: {exc}"

        if not os.path.isdir(dst):
            return False, f"Destination path is not a directory:\n{dst}"

        if not os.access(dst, os.W_OK):
            return False, f"Destination folder is not writable (permission denied):\n{dst}"

        return True, ""

    # ------------------------------------------------------------------ #
    # Single-Action Organization Execution
    # ------------------------------------------------------------------ #
    def _on_start_organization(self) -> None:
        valid, err_msg = self._validate_inputs()
        if not valid:
            QMessageBox.warning(self, "Validation Error", err_msg)
            return

        src_dir = os.path.abspath(self.source_edit.text().strip())
        dest_dir = os.path.abspath(self.dest_edit.text().strip())
        threshold = int(self.threshold_combo.currentData() or 50)
        only_groups = self.only_groups_check.isChecked()

        # Update UI state
        self.start_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setStyleSheet("color: #2563eb; font-weight: bold;")
        self.status_label.setText("Starting content analysis…")
        self.table.setRowCount(0)

        # Launch worker thread — pass retrieval_engine so FAISS embeddings are used
        self._worker = OrganizeWorkerThread(
            organizer=self._organizer,
            source_dir=src_dir,
            dest_dir=dest_dir,
            threshold=threshold,
            only_groups=only_groups,
            retrieval_engine=self._retrieval_engine,
        )
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.completed.connect(self._on_worker_completed)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()


    def _on_cancel(self) -> None:
        if self._worker and self._worker.isRunning():
            self.cancel_btn.setEnabled(False)
            self.status_label.setText("Cancelling organization…")
            self._worker.cancel()

    def _on_worker_progress(self, current: int, total: int, message: str) -> None:
        self.progress_bar.setValue(current)
        self.status_label.setText(message)

    def _on_worker_completed(self, result: dict) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.progress_bar.setVisible(False)
        self._last_result = result

        moved_count = result.get("moved_count", 0)
        folder_count = result.get("folder_count", 0)
        clusters = result.get("clusters", [])
        errors = result.get("errors", [])

        # Populate results table
        self.table.setRowCount(0)
        for row_idx, cluster in enumerate(clusters):
            self.table.insertRow(row_idx)

            # Folder Name
            name_item = QTableWidgetItem(f"📁 {cluster.folder_name}")
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row_idx, 0, name_item)

            # Relationship %
            pct_str = f"{cluster.similarity_percentage}%" if cluster.is_relation_cluster else "Independent"
            pct_item = QTableWidgetItem(pct_str)
            pct_item.setTextAlignment(Qt.AlignCenter)
            pct_item.setFlags(Qt.ItemIsEnabled)
            if cluster.similarity_percentage >= 50:
                pct_item.setForeground(Qt.darkGreen)
            self.table.setItem(row_idx, 1, pct_item)

            # File Count
            count_item = QTableWidgetItem(str(len(cluster.files)))
            count_item.setTextAlignment(Qt.AlignCenter)
            count_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row_idx, 2, count_item)

            # Files in Group
            file_names = ", ".join(os.path.basename(f) for f in cluster.files)
            files_item = QTableWidgetItem(file_names)
            files_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            files_item.setData(Qt.UserRole, cluster.files)
            self.table.setItem(row_idx, 3, files_item)

        if moved_count > 0:
            self.status_label.setStyleSheet("color: #16a34a; font-weight: bold;")
            self.status_label.setText(
                f"✓ Successfully organized {moved_count} file(s) into {folder_count} group folder(s)!"
            )
            QMessageBox.information(
                self,
                "Organization Complete",
                f"Successfully organized {moved_count} file(s) into {folder_count} group folder(s) in:\n\n"
                f"'{self.dest_edit.text().strip()}'\n\n"
                f"The folder structure has been updated.",
            )
            self.organization_completed.emit(result)
        else:
            msg = result.get("message") or "No files were moved."
            if errors:
                msg += "\n" + "\n".join(errors[:5])
            self.status_label.setStyleSheet("color: #d97706; font-weight: bold;")
            self.status_label.setText(msg)
            QMessageBox.information(self, "Organization Finished", msg)

    def _on_worker_error(self, err_msg: str) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.progress_bar.setVisible(False)
        self.status_label.setStyleSheet("color: #dc2626; font-weight: bold;")
        self.status_label.setText(f"Error: {err_msg}")
        QMessageBox.critical(self, "Organization Error", f"An error occurred during organization:\n\n{err_msg}")

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        files_item = self.table.item(row, 3)
        if files_item:
            files = files_item.data(Qt.UserRole)
            if files and self._open_file_callback:
                self._open_file_callback(files[0])


# Aliases for backward compatibility
OrganizeFileDialog = OrganizeDialog
