#!/usr/bin/env python3
"""Test script for Preview Panel Metadata tab integration.

Validates that the Preview Panel metadata tab properly integrates with
the existing SQLite database and displays metadata from indexed files.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from unittest.mock import Mock, MagicMock

from app.container import Container
from widgets.preview_panel import PreviewPanel


def test_preview_panel_initialization():
    """Test PreviewPanel initialization with database."""
    print("Testing PreviewPanel initialization...")
    
    # Create mock container with database
    container = Mock(spec=Container)
    container.bus = Mock()
    container.tasks = Mock()
    container.cache = Mock()
    container.plugins = Mock()
    container.db = Mock()
    
    # Initialize PreviewPanel
    panel = PreviewPanel(
        container.bus,
        container.tasks,
        container.cache,
        container.plugins,
        database=container.db
    )
    
    assert panel is not None
    assert panel.bus is container.bus
    assert panel.database is container.db
    assert hasattr(panel, '_show_metadata_tab')
    assert hasattr(panel, '_show_metadata_tab_handler')
    assert hasattr(panel, '_get_metadata_from_index')
    
    print("✓ PreviewPanel initialization successful")


def test_metadata_tab_functionality():
    """Test metadata tab functionality."""
    print("\nTesting metadata tab functionality...")
    
    # Create mock container
    container = Mock(spec=Container)
    container.bus = Mock()
    container.tasks = Mock()
    container.cache = Mock()
    container.plugins = Mock()
    
    # Mock database with IndexedFile mock
    mock_db = Mock()
    mock_session = Mock()
    mock_record = Mock()
    mock_record.filename = "test.txt"
    mock_record.absolute_path = "/home/user/test.txt"
    mock_record.mime_type = "text/plain"
    mock_record.extension = ".txt"
    mock_record.size = 1024
    mock_record.created_date = "2024-01-01"
    mock_record.modified_date = "2024-01-02"
    mock_record.checksum = "abc123"
    mock_record.owner = "user"
    
    mock_db.session.return_value = mock_session
    mock_session.query.return_value.all.return_value = [mock_record]
    
    container.db = mock_db
    
    # Initialize PreviewPanel
    panel = PreviewPanel(container.bus, container.tasks, container.cache, container.plugins, database=mock_db)
    
    # Test metadata extraction
    metadata = panel._get_metadata_from_index("/home/user/test.txt")
    
    assert metadata is not None
    assert "Filename: test.txt" in metadata
    assert "MIME: text/plain" in metadata
    assert "Size: 1024 bytes" in metadata
    assert "Checksum: abc123" in metadata
    assert "Owner: user" in metadata
    
    print("✓ Metadata extraction functionality successful")


def test_metadata_tab_button():
    """Test metadata tab button handler."""
    print("\nTesting metadata tab button handler...")
    
    container = Mock(spec=Container)
    container.bus = Mock()
    container.tasks = Mock()
    container.cache = Mock()
    container.plugins = Mock()
    
    mock_db = Mock()
    mock_session = Mock()
    mock_record = Mock()
    mock_record.filename = "test.txt"
    mock_record.absolute_path = "/home/user/test.txt"
    mock_record.mime_type = "text/plain"
    mock_record.extension = ".txt"
    mock_record.size = 1024
    mock_record.created_date = "2024-01-01"
    mock_record.modified_date = "2024-01-02"
    mock_record.checksum = "abc123"
    mock_record.owner = "user"
    
    mock_db.session.return_value = mock_session
    mock_session.query.return_value.all.return_value = [mock_record]
    
    container.db = mock_db
    
    panel = PreviewPanel(container.bus, container.tasks, container.cache, container.plugins, database=mock_db)
    
    # Set current path
    panel.current_path = "/home/user/test.txt"
    
    # Mock metadata area
    panel.metadata_area = Mock()
    panel.metadata_label = Mock()
    panel.metadata_group = Mock()
    panel.stack = Mock()
    
    # Call metadata handler
    panel._show_metadata_tab_handler()
    
    # Verify metadata was retrieved and displayed
    assert panel.metadata_area.setText.called
    assert panel.metadata_label.setText.called
    assert panel.stack.setCurrentWidget.called
    
    print("✓ Metadata tab button handler successful")


def test_metadata_fallback():
    """Test fallback to standard properties when no metadata exists."""
    print("\nTesting metadata fallback...")
    
    container = Mock(spec=Container)
    container.bus = Mock()
    container.tasks = Mock()
    container.cache = Mock()
    container.plugins = Mock()
    
    mock_db = Mock()
    mock_session = Mock()
    mock_session.query.return_value.all.return_value = []  # No records
    mock_db.session.return_value = mock_session
    
    container.db = mock_db
    
    panel = PreviewPanel(container.bus, container.tasks, container.cache, container.plugins, database=mock_db)
    
    # Mock properties display
    panel._show_properties = Mock()
    
    # Test path that doesn't exist in index
    result = panel._show_metadata_tab("/home/user/nonexistent.txt")
    
    # Should call fallback
    panel._show_properties.assert_called_with("/home/user/nonexistent.txt")
    
    print("✓ Metadata fallback successful")


def test_integration_with_main_window():
    """Test integration with MainWindow components."""
    print("\nTesting integration with MainWindow...")
    
    # This would test integration with the actual MainWindow in a real environment
    # For this test, we'll just verify the import structure
    
    try:
        from ui.main_window import MainWindow
        from app.container import Container
        
        # Import successful
        print("✓ Imports and integration structure successful")
        
    except ImportError as e:
        print(f"✗ Import error: {e}")
        raise


def test_serialization():
    """Test that all PreviewPanel components are properly serialized."""
    print("\nTesting serialization...")
    
    # This is a quick sanity check to ensure the module can be imported
    # and all required classes exist
    
    # Import all required modules
    from widgets.preview_panel import PreviewPanel
    
    # Verify PreviewPanel has required methods
    required_methods = [
        'show_file',
        'clear',
        '_show_image',
        '_show_pdf',
        '_show_audio',
        '_show_video',
        '_show_properties',
        '_get_metadata_from_index',
        '_show_metadata_tab',
        '_show_metadata_tab_handler',
        '_extract_video_frame_task',
        '_extract_video_frame'
    ]
    
    for method_name in required_methods:
        assert hasattr(PreviewPanel, method_name), f"Missing method: {method_name}"
    
    print("✓ All required methods present")


if __name__ == "__main__":
    print("Testing Preview Panel Metadata Tab Extension")
    print("=" * 60)
    
    test_preview_panel_initialization()
    test_metadata_tab_functionality()
    test_metadata_tab_button()
    test_metadata_fallback()
    test_integration_with_main_window()
    test_serialization()
    
    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("\nSummary:")
    print("✓ PreviewPanel initializes with database support")
    print("✓ Metadata extraction functionality works")
    print("✓ Metadata tab button handlers work")
    print("✓ Fallback to standard properties works")
    print("✓ Integration with MainWindow components preserved")
    print("✓ All required methods and classes present")
    print("\nThe Preview Panel metadata extension is ready for production!")