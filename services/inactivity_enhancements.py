"""
Phase 2.2: Inactivity Settings Enhancement
Adds configuration UI, reset capabilities, and testing features
"""

from datetime import datetime, timedelta
from dataclasses import dataclass


@dataclass
class InactiveFileInfo:
    """Information about an inactive file"""
    file_path: str
    days_inactive: int
    last_accessed: datetime
    file_size: int


class InactivityReminderEnhancements:
    """Enhancements for InactivityReminderService"""
    
    @staticmethod
    def add_to_service():
        """Methods to add to InactivityReminderService class"""
        pass


# METHODS TO ADD TO InactivityReminderService CLASS:

def reset_reminder_state(self):
    """
    Reset all inactivity reminder state
    Useful for testing the feature
    """
    if hasattr(self, 'last_reminder_shown'):
        self.last_reminder_shown.clear()
    
    # Clear from database if available
    try:
        if self.repository and hasattr(self.repository, 'session'):
            from database.models import InactivityReminder
            session = self.repository.session
            session.query(InactivityReminder).delete()
            session.commit()
    except Exception as e:
        print(f"Could not clear DB reminders: {e}")


def find_inactive_files(self, days: int = None, include_size: bool = True):
    """
    Find all files not accessed in N days
    
    SCOPE: ALL files in workspace (entire workspace, not current directory)
    
    Args:
        days: Days of inactivity (uses default if None)
        include_size: Whether to include file size info
    
    Returns:
        List of InactiveFileInfo objects
    """
    if days is None:
        days = self.days_threshold
    
    try:
        from database.models import File
        
        threshold_date = datetime.now() - timedelta(days=days)
        
        # Query all files with last_accessed before threshold
        query_result = self.repository.session.query(File).filter(
            File.last_accessed < threshold_date
        ).all()
        
        inactive_files = []
        for file_record in query_result:
            if not file_record.path or not file_record.last_accessed:
                continue
            
            try:
                days_inactive = (datetime.now() - file_record.last_accessed).days
                
                info = InactiveFileInfo(
                    file_path=file_record.path,
                    days_inactive=days_inactive,
                    last_accessed=file_record.last_accessed,
                    file_size=getattr(file_record, 'size_bytes', 0) if include_size else 0
                )
                inactive_files.append(info)
            except Exception as e:
                print(f"Error processing file {file_record.path}: {e}")
                continue
        
        # Sort by days inactive (most inactive first)
        inactive_files.sort(key=lambda f: f.days_inactive, reverse=True)
        
        return inactive_files
    
    except Exception as e:
        print(f"Error finding inactive files: {e}")
        return []


def mark_file_accessed(self, file_path: str):
    """
    Mark a file as recently accessed
    Resets its inactivity timer
    
    Args:
        file_path: Path to the file
    """
    try:
        from database.models import File
        
        file_record = self.repository.session.query(File).filter(
            File.path == file_path
        ).first()
        
        if file_record:
            file_record.last_accessed = datetime.now()
            self.repository.session.commit()
    
    except Exception as e:
        print(f"Error marking file accessed: {e}")


def get_inactive_stats(self, days: int = None) -> dict:
    """
    Get statistics about inactive files
    
    Args:
        days: Days threshold (uses default if None)
    
    Returns:
        Dictionary with stats
    """
    if days is None:
        days = self.days_threshold
    
    try:
        inactive_files = self.find_inactive_files(days)
        
        if not inactive_files:
            return {
                'total_inactive': 0,
                'total_size': 0,
                'oldest_inactive': None,
                'most_recent_inactive': None,
                'average_days': 0
            }
        
        total_size = sum(f.file_size for f in inactive_files)
        days_list = [f.days_inactive for f in inactive_files]
        
        return {
            'total_inactive': len(inactive_files),
            'total_size': total_size,
            'oldest_inactive': inactive_files[0].days_inactive,
            'most_recent_inactive': inactive_files[-1].days_inactive,
            'average_days': sum(days_list) / len(days_list) if days_list else 0
        }
    
    except Exception as e:
        print(f"Error getting stats: {e}")
        return {}


# SETTINGS DIALOG ADDITIONS:

settings_ui_code = """
# Add this to ui/settings_dialog.py - SettingsDialog class:

def _batch7_tab(self) -> QWidget:
    '''Settings for inactivity reminder'''
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
        QSpinBox, QCheckBox, QPushButton, QLabel, QMessageBox
    )
    
    tab = QWidget()
    layout = QVBoxLayout()
    
    # ============ SECTION 1: INFORMATION ============
    info_group = QGroupBox("About Inactivity Reminder")
    info_layout = QVBoxLayout()
    
    explanation = QLabel(
        "The Inactivity Reminder monitors ALL files in your workspace.\\n"
        "It alerts you about files that haven't been accessed recently.\\n\\n"
        "SCOPE: Entire workspace (all indexed files across all folders)\\n"
        "NOT just the current directory - your whole workspace!"
    )
    explanation.setWordWrap(True)
    explanation.setStyleSheet("color: #0078d4; font-weight: bold;")
    info_layout.addWidget(explanation)
    info_group.setLayout(info_layout)
    
    # ============ SECTION 2: CONFIGURATION ============
    config_group = QGroupBox("Configuration")
    config_layout = QVBoxLayout()
    
    # Days threshold
    threshold_layout = QHBoxLayout()
    threshold_layout.addWidget(QLabel("Mark files as inactive after:"))
    
    self.inactivity_days_spinbox = QSpinBox()
    self.inactivity_days_spinbox.setMinimum(1)
    self.inactivity_days_spinbox.setMaximum(365)
    self.inactivity_days_spinbox.setValue(30)
    self.inactivity_days_spinbox.setSuffix(" days")
    self.inactivity_days_spinbox.setToolTip("Files not accessed in N days are marked inactive")
    
    threshold_layout.addWidget(self.inactivity_days_spinbox)
    threshold_layout.addStretch()
    config_layout.addLayout(threshold_layout)
    
    # Enable/disable
    self.inactivity_enabled_checkbox = QCheckBox("Enable inactivity reminders")
    self.inactivity_enabled_checkbox.setChecked(True)
    self.inactivity_enabled_checkbox.setToolTip("Turn off to disable the reminder system")
    config_layout.addWidget(self.inactivity_enabled_checkbox)
    
    config_group.setLayout(config_layout)
    
    # ============ SECTION 3: TESTING ============
    testing_group = QGroupBox("Testing & Debugging")
    testing_layout = QVBoxLayout()
    
    testing_info = QLabel(
        "Use these buttons to test the inactivity reminder feature:\\n"
        "• Reset: Clears all reminder history (allows re-testing)\\n"
        "• Check Now: Manually scan for inactive files"
    )
    testing_info.setWordWrap(True)
    testing_layout.addWidget(testing_info)
    
    # Buttons
    buttons_layout = QHBoxLayout()
    
    reset_button = QPushButton("Reset Reminder State")
    reset_button.setToolTip("Clear all reminder history for testing")
    reset_button.clicked.connect(self._reset_inactivity_reminder)
    
    check_button = QPushButton("Manually Check for Inactive Files")
    check_button.setToolTip("Scan workspace for inactive files with current threshold")
    check_button.clicked.connect(self._manually_check_inactive)
    
    buttons_layout.addWidget(reset_button)
    buttons_layout.addWidget(check_button)
    testing_layout.addLayout(buttons_layout)
    
    testing_group.setLayout(testing_layout)
    
    # ============ ASSEMBLE ============
    layout.addWidget(info_group)
    layout.addWidget(config_group)
    layout.addWidget(testing_group)
    layout.addStretch()
    
    tab.setLayout(layout)
    return tab


def _reset_inactivity_reminder(self):
    '''Reset reminder for testing'''
    reply = QMessageBox.question(
        self,
        "Reset Inactivity Reminder",
        "This will clear all inactivity reminder history.\\n"
        "You can then test the feature again.\\n\\n"
        "Are you sure?",
        QMessageBox.Yes | QMessageBox.No
    )
    
    if reply == QMessageBox.Yes:
        try:
            self.container.inactivity_reminder_service.reset_reminder_state()
            QMessageBox.information(
                self,
                "Success",
                "Inactivity reminder state has been reset!\\n"
                "You can now test the feature again."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to reset: {str(e)}")


def _manually_check_inactive(self):
    '''Manually trigger inactivity check'''
    try:
        days = self.inactivity_days_spinbox.value()
        inactive_files = self.container.inactivity_reminder_service.find_inactive_files(days)
        
        if not inactive_files:
            QMessageBox.information(
                self,
                "No Inactive Files",
                f"No files found inactive for more than {days} days\\n\\n"
                f"Your workspace files are all actively used!"
            )
        else:
            message = f"Found {len(inactive_files)} inactive files (not accessed in {days}+ days):\\n\\n"
            
            for i, f in enumerate(inactive_files[:10], 1):
                size_mb = f.file_size / (1024 * 1024)
                message += f"{i}. {f.file_path}\\n"
                message += f"   Inactive: {f.days_inactive} days | Size: {size_mb:.1f} MB\\n\\n"
            
            if len(inactive_files) > 10:
                message += f"\\n... and {len(inactive_files) - 10} more files"
            
            QMessageBox.information(self, "Inactive Files", message)
    
    except Exception as e:
        QMessageBox.critical(self, "Error", f"Failed to check: {str(e)}")
"""
