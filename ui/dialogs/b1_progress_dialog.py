"""Batch 1 Progress Dialog.

Progress dialog for the Batch 1 File Scan with detailed statistics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QListWidget,
    QPushButton,
    QDialogButtonBox,
    QGroupBox,
    QFormLayout,
)


class B1ProgressDialog(QDialog):
    """Progress dialog for Batch 1 file scanning with detailed statistics."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._start_time = datetime.now()
        self._file_count = 0
        self._processed_count = 0
        self._speed_calc_time = datetime.now()
        self._last_file_count = 0

        self.setWindowTitle("Batch 1 - File Scan")
        self.resize(600, 500)
        self.setModal(True)

        self._setup_ui()
        self._setup_timers()

    def _setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)

        # Current File Display
        file_display_group = QGroupBox("Current File")
        file_layout = QVBoxLayout(file_display_group)

        self.current_file_label = QLabel("Starting scan...")
        self.current_file_label.setWordWrap(True)
        self.current_file_label.setStyleSheet("font-weight: bold; color: #2E7D32;")
        file_layout.addWidget(self.current_file_label)

        layout.addWidget(file_display_group)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate until we know total
        layout.addWidget(self.progress_bar)

        # Statistics Group
        stats_group = QGroupBox("Statistics")
        stats_layout = QFormLayout(stats_group)

        # File Count
        self.total_files_label = QLabel("0 files")
        stats_layout.addRow("Total Files:", self.total_files_label)

        # ETA
        self.eta_label = QLabel("ETA: Calculating...")
        stats_layout.addRow("Estimated Time Remaining:", self.eta_label)

        # Processing Rate
        self.rate_label = QLabel("Rate: 0 files/sec")
        stats_layout.addRow("Processing Rate:", self.rate_label)

        # Processing Time
        self.time_label = QLabel("Time Elapsed: 0s")
        stats_layout.addRow("Time Elapsed:", self.time_label)

        # Processed Items
        self.processed_label = QLabel("0 processed")
        stats_layout.addRow("Items Processed:", self.processed_label)

        layout.addWidget(stats_group)

        # Files List
        list_group = QGroupBox("Processed Files")
        list_layout = QVBoxLayout(list_group)

        self.files_list = QListWidget()
        list_layout.addWidget(self.files_list)

        layout.addWidget(list_group)

        # Button Box
        button_box = QDialogButtonBox(QDialogButtonBox.Cancel)
        button_box.rejected.connect(self.reject)
        self.cancel_button = button_box.buttons()[0]
        layout.addWidget(button_box)

    def _setup_timers(self):
        """Set up timers for updating statistics."""
        self.timer = self._start_time
        from PySide6.QtCore import QTimer

        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._update_statistics)
        self.update_timer.start(100)  # Update every 100ms

    def _update_statistics(self):
        """Update statistics labels."""
        now = datetime.now()
        elapsed = (now - self._start_time).total_seconds()

        # Update time elapsed
        mins, secs = divmod(int(elapsed), 60)
        self.time_label.setText(f"Time Elapsed: {mins}m {secs}s")

        # Calculate processing rate (files per second)
        if elapsed > 0:
            self._file_count = self._processed_count
            rate = self._file_count / elapsed
            self.rate_label.setText(f"Rate: {rate:.1f} files/sec")

            # Calculate ETA
            if hasattr(self, '_total_files') and self._total_files > 0:
                remaining = self._total_files - self._processed_count
                if rate > 0:
                    eta_seconds = remaining / rate
                    eta_mins, eta_secs = divmod(int(eta_seconds), 60)
                    if eta_mins > 0:
                        eta_text = f"ETA: {eta_mins}m {eta_secs}s"
                    else:
                        eta_text = f"ETA: {eta_secs}s"
                    self.eta_label.setText(eta_text)

        # Update processed label
        self.processed_label.setText(f"{self._processed_count} processed")

    def update_progress(self, processed: int, total: int):
        """Update progress information."""
        self._processed_count = processed
        self._total_files = total

        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(processed)
            self.total_files_label.setText(f"{processed}/{total} files")

            # Calculate percentage
            percentage = (processed / total) * 100
            self.progress_bar.setFormat(f"%{percentage:.1f}")

    def set_current_file(self, file_path: str):
        """Set the current file being processed."""
        filename = file_path.split('/')[-1] if '/' in file_path else file_path
        self.current_file_label.setText(f"Processing: {filename}")

        # Add to list with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.files_list.addItem(f"[{timestamp}] {filename}")

        # Keep list limited to 50 items
        if self.files_list.count() > 50:
            self.files_list.takeItem(0)

    def update_status(self, status: str):
        """Update the status label."""
        self.current_file_label.setText(status)

    def set_cancel_button_enabled(self, enabled: bool):
        """Enable or disable the cancel button."""
        self.cancel_button.setEnabled(enabled)
        if not enabled:
            self.cancel_button.setText("Cancel (Cannot cancel)")

    def closeEvent(self, event):
        """Handle close event to clean up timers."""
        self.update_timer.stop()
        super().closeEvent(event)