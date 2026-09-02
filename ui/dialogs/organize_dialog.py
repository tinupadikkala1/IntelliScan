"""User-Directed & Automatic Content-Based File Organization Dialog.

Partition workspace files into N relation clusters (>= 50% content overlap)
and M independent items (< 50% overlap).
Automatically names target folders based on core topic content and moves files.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from services.file_organizer_service import (
    FileOrganizerService,
    OrganizationCandidate,
    ProposedFolderCluster,
)



class ClusterWorker(QThread):
    """Background worker thread for content-based folder clustering."""

    clusters_found = Signal(list)
    cluster_error = Signal(str)

    def __init__(self, organizer, dest_dir: str, threshold: int) -> None:
        super().__init__()
        self.organizer = organizer
        self.dest_dir = dest_dir
        self.threshold = threshold

    def run(self) -> None:
        try:
            clusters = self.organizer.auto_cluster_folder(
                folder_path=self.dest_dir,
                min_similarity=self.threshold,
            )
            self.clusters_found.emit(clusters)
        except Exception as exc:
            self.cluster_error.emit(str(exc))


class OrganizeDialog(QDialog):
    """Dialog for automatic content-based N+M folder organization."""

    organization_completed = Signal(dict)

    def __init__(
        self,
        organizer_service: FileOrganizerService,
        current_dir: str = "",
        open_file_callback: Optional[Callable[[str], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._organizer = organizer_service
        self._current_dir = os.path.abspath(current_dir) if current_dir else os.path.expanduser("~")
        self._open_file_callback = open_file_callback
        self._clusters: List[ProposedFolderCluster] = []
        self._worker: Optional[ClusterWorker] = None

        self.setWindowTitle("Automatic Content Folder Organization")
        self.setMinimumSize(920, 640)
        self.setModal(False)
        self._setup_ui()


    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header instructions
        title_label = QLabel("📁 Automatic Content-Based Folder Organization")
        title_label.setStyleSheet("font-size: 15px; font-weight: bold; padding: 4px;")
        layout.addWidget(title_label)

        desc_label = QLabel(
            "The system detects content relationships (>= 50% similarity) across workspace files. "
            "Related files are grouped into N relation folders, while independent files (< 50% similarity) "
            "are grouped into M dedicated folders named after their core content."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #475569; padding-bottom: 8px;")
        layout.addWidget(desc_label)

        # Controls
        # 1. Similarity Threshold
        thresh_layout = QHBoxLayout()
        thresh_lbl = QLabel("Relationship Threshold:")
        thresh_lbl.setFixedWidth(160)
        self.threshold_combo = QComboBox()
        self.threshold_combo.addItem("Strict (50% Overlap Threshold)", 50)
        self.threshold_combo.addItem("Medium (40% Overlap Threshold)", 40)
        self.threshold_combo.addItem("High Precision (60% Overlap Threshold)", 60)
        thresh_layout.addWidget(thresh_lbl)
        thresh_layout.addWidget(self.threshold_combo, 1)
        layout.addLayout(thresh_layout)

        # 2. Destination Parent Directory
        dest_layout = QHBoxLayout()
        dest_lbl = QLabel("Destination Location:")
        dest_lbl.setFixedWidth(160)
        self.dest_edit = QLineEdit(self._current_dir)
        browse_btn = QPushButton("Browse...")
        browse_btn.setAutoDefault(False)
        browse_btn.setDefault(False)
        browse_btn.clicked.connect(self._browse_destination)
        dest_layout.addWidget(dest_lbl)
        dest_layout.addWidget(self.dest_edit, 1)
        dest_layout.addWidget(browse_btn)
        layout.addLayout(dest_layout)

        # Scan button
        scan_bar = QHBoxLayout()
        self.scan_btn = QPushButton("🔍 Scan Content & Detect N+M Folder Structure")
        self.scan_btn.setAutoDefault(False)
        self.scan_btn.setDefault(False)
        self.scan_btn.setStyleSheet("font-weight: bold; padding: 6px 14px; background-color: #2563eb; color: white;")
        self.scan_btn.clicked.connect(self._on_scan)
        scan_bar.addWidget(self.scan_btn)
        scan_bar.addStretch(1)
        self.status_label = QLabel("")
        scan_bar.addWidget(self.status_label)
        layout.addLayout(scan_bar)

        # Proposed Clusters Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Select", "Proposed Folder Name", "Group Type", "Overlap %", "File Count", "Matching Files / Reason"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 240)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table, 1)

        # Bottom Actions
        bottom_bar = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setAutoDefault(False)
        self.select_all_btn.setDefault(False)
        self.select_all_btn.clicked.connect(lambda: self._set_all_selected(True))

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.setAutoDefault(False)
        self.deselect_all_btn.setDefault(False)
        self.deselect_all_btn.clicked.connect(lambda: self._set_all_selected(False))

        bottom_bar.addWidget(self.select_all_btn)
        bottom_bar.addWidget(self.deselect_all_btn)
        bottom_bar.addStretch(1)

        self.execute_btn = QPushButton("📁 Create N+M Folders & Move Files")
        self.execute_btn.setAutoDefault(False)
        self.execute_btn.setDefault(False)
        self.execute_btn.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold; padding: 6px 18px;")
        self.execute_btn.clicked.connect(self._on_execute)
        self.execute_btn.setEnabled(False)

        close_btn = QPushButton("Close")
        close_btn.setAutoDefault(False)
        close_btn.setDefault(False)
        close_btn.clicked.connect(self.accept)

        bottom_bar.addWidget(self.execute_btn)
        bottom_bar.addWidget(close_btn)
        layout.addLayout(bottom_bar)

        # Auto-scan destination on dialog launch
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self._on_scan)


        self.threshold_combo.currentIndexChanged.connect(lambda: self._on_scan())

    def _browse_destination(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, "Select Destination Parent Directory", self.dest_edit.text())
        if dir_path:
            self.dest_edit.setText(dir_path)
            self._on_scan()

    def _on_scan(self) -> None:
        dest_dir = self.dest_edit.text().strip()
        if not os.path.isdir(dest_dir):
            self.status_label.setText("Please select a valid folder directory using Browse...")
            self.status_label.setStyleSheet("color: #dc2626;")
            return

        threshold = self.threshold_combo.currentData() or 50
        self.status_label.setText("Scanning & partitioning N+M clusters in background...")
        self.status_label.setStyleSheet("color: #2563eb;")
        self.scan_btn.setEnabled(False)

        # Cancel any previous active worker
        if self._worker is not None and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()

        # Start background worker thread
        self._worker = ClusterWorker(self._organizer, dest_dir, threshold)
        self._worker.clusters_found.connect(self._on_scan_finished)
        self._worker.cluster_error.connect(self._on_scan_error)
        self._worker.start()

    def _on_scan_finished(self, clusters: list) -> None:
        self.scan_btn.setEnabled(True)
        self._clusters = clusters
        self._populate_table()

        if not clusters:
            self.status_label.setText("No files found in selected folder. Click Browse... to select a folder with files.")
            self.status_label.setStyleSheet("color: #ea580c;")
            self.execute_btn.setEnabled(False)
        else:
            num_rel = sum(1 for c in clusters if c.is_relation_cluster)
            num_ind = sum(1 for c in clusters if not c.is_relation_cluster)
            self.status_label.setText(f"Detected {len(clusters)} Folders ({num_rel} Relation Groups + {num_ind} Independent Folders)")
            self.status_label.setStyleSheet("color: #16a34a;")
            self.execute_btn.setEnabled(True)

    def _on_scan_error(self, err_msg: str) -> None:
        self.scan_btn.setEnabled(True)
        self.status_label.setText(f"Clustering failed: {err_msg}")
        self.status_label.setStyleSheet("color: #dc2626;")



    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        for row_idx, cluster in enumerate(self._clusters):
            self.table.insertRow(row_idx)

            # Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked if cluster.selected else Qt.Unchecked)
            self.table.setItem(row_idx, 0, chk_item)

            # Proposed Folder Name (Editable)
            name_item = QTableWidgetItem(cluster.folder_name)
            name_item.setFlags(Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row_idx, 1, name_item)

            # Group Type
            type_str = "🔗 N Relation Cluster" if cluster.is_relation_cluster else "📄 M Independent Folder"
            type_item = QTableWidgetItem(type_str)
            type_item.setFlags(Qt.ItemIsEnabled)
            if cluster.is_relation_cluster:
                type_item.setForeground(Qt.darkBlue)
            else:
                type_item.setForeground(Qt.darkGray)
            self.table.setItem(row_idx, 2, type_item)

            # Overlap %
            pct_str = f"{cluster.similarity_percentage}%" if cluster.is_relation_cluster else "0%"
            pct_item = QTableWidgetItem(pct_str)
            pct_item.setTextAlignment(Qt.AlignCenter)
            pct_item.setFlags(Qt.ItemIsEnabled)
            if cluster.similarity_percentage >= 50:
                pct_item.setForeground(Qt.darkGreen)
            self.table.setItem(row_idx, 3, pct_item)

            # File Count
            count_item = QTableWidgetItem(str(len(cluster.files)))
            count_item.setTextAlignment(Qt.AlignCenter)
            count_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row_idx, 4, count_item)

            # Files / Reason
            file_names = ", ".join(os.path.basename(f) for f in cluster.files[:3])
            if len(cluster.files) > 3:
                file_names += f" (+{len(cluster.files)-3} more)"
            reason_str = f"{file_names} — {cluster.reason}"
            reason_item = QTableWidgetItem(reason_str)
            reason_item.setFlags(Qt.ItemIsEnabled)
            reason_item.setData(Qt.UserRole, cluster.files)
            self.table.setItem(row_idx, 5, reason_item)

    def _set_all_selected(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(state)

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        reason_item = self.table.item(row, 5)
        if reason_item:
            files = reason_item.data(Qt.UserRole)
            if files and self._open_file_callback:
                self._open_file_callback(files[0])

    def _on_execute(self) -> None:
        dest_parent = self.dest_edit.text().strip()
        if not os.path.isdir(dest_parent):
            QMessageBox.warning(self, "Invalid Destination", f"Destination directory does not exist:\n{dest_parent}")
            return

        # Synchronize folder names from editable table column
        for row in range(self.table.rowCount()):
            chk = self.table.item(row, 0)
            name_item = self.table.item(row, 1)
            if row < len(self._clusters):
                self._clusters[row].selected = (chk and chk.checkState() == Qt.Checked)
                if name_item and name_item.text().strip():
                    self._clusters[row].folder_name = name_item.text().strip()

        selected_clusters = [c for c in self._clusters if c.selected and c.files]
        if not selected_clusters:
            QMessageBox.warning(self, "No Clusters Selected", "Please select at least one proposed folder to organize.")
            return

        total_files = sum(len(c.files) for c in selected_clusters)
        confirm = QMessageBox.question(
            self,
            "Confirm Organization",
            f"Are you sure you want to create {len(selected_clusters)} folder(s) and move {total_files} file(s) into:\n\n"
            f"'{dest_parent}'?\n\n"
            f"Files will be partitioned into N relation folders and M independent folders based on content similarity.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        res = self._organizer.execute_auto_clustering(
            clusters=selected_clusters,
            destination_parent_dir=dest_parent,
        )

        if res.get("ok"):
            QMessageBox.information(
                self,
                "Organization Complete",
                f"Successfully created {res['folder_count']} folder(s) and moved {res['moved_count']} file(s) into:\n\n"
                f"'{dest_parent}'",
            )
            self.organization_completed.emit(res)
            self.accept()
        else:
            QMessageBox.critical(self, "Organization Failed", res.get("error", "An error occurred."))
