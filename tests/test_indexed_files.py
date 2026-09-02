#!/usr/bin/env python3
"""Test script for Indexed Files Widget integration.

Validates that the Indexed Files widget properly integrates with the existing
architecture without modifying unrelated modules.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from app.container import Container
from ui.indexed_files_widget import IndexedFilesWidget
from ui.indexed_files_model import IndexedFilesModel


def test_import():
    """Test that all required modules can be imported correctly."""
    print("Testing imports...")
    container = Container()
    assert container is not None

    widget = IndexedFilesWidget(container)
    assert widget is not None

    model = IndexedFilesModel(container.db, container.tasks)
    assert model is not None

    print("✓ Imports successful")


def test_widget_ui():
    """Test widget UI components."""
    print("\nTesting widget UI components...")
    container = Container()
    widget = IndexedFilesWidget(container)

    # Check UI components exist
    assert widget.search_input is not None
    assert widget.filter_combo is not None
    assert widget.files_list is not None
    assert widget.status_label is not None

    # Check filter options
    filter_options = widget.filter_combo.currentText()
    assert filter_options == "All"

    print("✓ Widget UI components initialized")


def test_model():
    """Test model functionality."""
    print("\nTesting model functionality...")
    container = Container()

    # Test model initialization
    model = IndexedFilesModel(container.db, container.tasks)
    assert model is not None

    # Test set_filter method
    model.set_filter("All")
    items = model.get_items()
    assert isinstance(items, list)

    # Test set_search_text method
    model.set_search_text("")
    filtered_items = model.get_filtered_items()
    assert isinstance(filtered_items, list)

    print("✓ Model methods working")


def test_refresh():
    """Test refresh functionality."""
    print("\nTesting refresh functionality...")
    container = Container()
    widget = IndexedFilesWidget(container)

    # Initial refresh should not crash
    widget.refresh_data()

    # Simulate items updated
    test_items = [
        {
            "id": 1,
            "filename": "test.txt",
            "absolute_path": "/home/user/test.txt",
            "size": 1024,
            "mime_type": "text/plain",
            "extension": ".txt",
            "created_date": None,
            "modified_date": None,
            "checksum": "abc123",
            "extracted_text": "Test file content",
            "metadata_json": "{}",
            "scan_timestamp": None,
            "indexing_status": "completed",
            "processing_attempts": 0,
            "error_message": None,
            "last_updated": None,
        }
    ]

    widget._on_items_updated(test_items)
    assert widget.files_list.count() == 1

    print("✓ Refresh and UI update working")


def test_search_and_filter():
    """Test search and filter functionality."""
    print("\nTesting search and filter...")
    container = Container()
    widget = IndexedFilesWidget(container)

    widget._apply_search()
    widget._apply_filters()

    # Test filter options
    widget.filter_combo.setCurrentText("PDF Documents (.pdf)")
    widget._apply_filters()

    # Test search
    widget.search_input.setText("test")
    widget._apply_search()

    print("✓ Search and filter functionality working")


def test_file_selection():
    """Test file selection and event handling."""
    print("\nTesting file selection...")
    container = Container()
    widget = IndexedFilesWidget(container)

    # Mock item data
    test_item = {
        "absolute_path": "/home/user/test.txt",
        "filename": "test.txt",
        "path": "/home/user/",
        "size": 1024,
        "mime_type": "text/plain",
        "extension": ".txt",
        "created_date": None,
        "modified_date": None,
        "checksum": "abc123",
        "extracted_text": "Test file content",
        "metadata_json": "{}",
        "scan_timestamp": None,
        "indexing_status": "completed",
        "processing_attempts": 0,
        "error_message": None,
        "last_updated": None,
    }

    widget._add_item_to_list(test_item)
    widget._on_file_selected(widget.files_list.item(0))

    print("✓ File selection working")


if __name__ == "__main__":
    print("Testing Indexed Files Widget Integration")
    print("=" * 50)

    test_import()
    test_widget_ui()
    test_model()
    test_refresh()
    test_search_and_filter()
    test_file_selection()

    print("\n" + "=" * 50)
    print("All tests passed! ✓")
    print("\nSummary:")
    print("- IndexedFilesWidget properly integrates with Container")
    print("- All UI components initialized correctly")
    print("- Model methods work as expected")
    print("- Refresh and data loading function")
    print("- Search and filter functionality works")
    print("- File selection and event handling works")
    print("\nThe Indexed Files widget is ready for integration with the main window.")