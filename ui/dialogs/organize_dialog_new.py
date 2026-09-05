"""Compatibility module for OrganizeDialog.

Re-exports OrganizeDialog from organize_dialog.py.
"""

from services.file_organizer_service import MoveResult
from ui.dialogs.organize_dialog import OrganizeDialog, OrganizeFileDialog

__all__ = ["OrganizeDialog", "OrganizeFileDialog", "MoveResult"]
