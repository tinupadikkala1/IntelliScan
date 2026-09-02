import os

import pytest
from PySide6.QtCore import QElapsedTimer, Qt
from PySide6.QtWidgets import QApplication

from app.container import Container
from ui.main_window import MainWindow
from widgets.preview_panel import PreviewPanel


def _wait(qapp, timeout=3000):
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < timeout:
        QApplication.processEvents()


def test_preview_panel_builds(qapp):
    PreviewPanel(Container().bus)


def test_preview_image(qapp, tmp_path):
    from PySide6.QtGui import QPixmap

    p = str(tmp_path / "img.png")
    pm = QPixmap(64, 64)
    pm.fill(Qt.red)
    assert pm.save(p, "PNG")
    panel = PreviewPanel(Container().bus)
    panel.show_file(p)
    assert panel.stack.currentWidget() is panel.image_label
    assert not panel.image_label.pixmap().isNull()


def test_preview_text(qapp, tmp_path):
    p = str(tmp_path / "note.txt")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("hello world")
    panel = PreviewPanel(Container().bus)
    panel.show_file(p)
    assert panel.stack.currentWidget() is panel.text_edit
    assert "hello world" in panel.text_edit.toPlainText()


def test_preview_pdf(qapp, tmp_path):
    # Minimal valid PDF.
    p = str(tmp_path / "doc.pdf")
    with open(p, "wb") as fh:
        fh.write(b"%PDF-1.1\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
    panel = PreviewPanel(Container().bus)
    panel.show_file(p)
    # Either the pdf view shown, or graceful fallback info.
    assert panel.stack.currentWidget() in (panel.pdf_view, panel.info_area)


def test_preview_audio_metadata(qapp, tmp_path):
    p = str(tmp_path / "sound.mp3")
    with open(p, "wb") as fh:
        fh.write(b"\x00\x00\x00\x00")
    panel = PreviewPanel(Container().bus)
    panel.show_file(p)
    assert panel.stack.currentWidget() is panel.info_area
    assert "Audio metadata" in panel.info_area.text()


def test_preview_properties_for_dir(qapp, tmp_path):
    panel = PreviewPanel(Container().bus)
    panel.show_file(str(tmp_path))
    assert "Folder" in panel.info_area.text()


def test_preview_clear(qapp):
    panel = PreviewPanel(Container().bus)
    panel.clear()
    assert panel.current_path == ""
    assert panel.stack.currentWidget() is panel.info_area


def test_preview_ai_placeholders_disabled(qapp):
    from PySide6.QtWidgets import QLabel

    panel = PreviewPanel(Container().bus)
    assert not panel.ai_group.isEnabled()
    labels = panel.ai_group.findChildren(QLabel)
    assert len(labels) == 4  # Summary, Keywords, OCR, Related files


def test_main_window_preview_wired(qapp, tmp_path):
    from PySide6.QtGui import QPixmap

    img = str(tmp_path / "x.png")
    pm = QPixmap(32, 32)
    pm.fill(Qt.blue)
    assert pm.save(img, "PNG")
    w = MainWindow(Container())
    w._on_selection_changed([img])
    assert w.preview.current_path == img
    assert w.preview.stack.currentWidget() is w.preview.image_label


def test_preview_extracted_text_on_the_fly_image(qapp, tmp_path):
    from PySide6.QtGui import QPixmap
    from unittest.mock import MagicMock

    img_path = str(tmp_path / "ocr_test.png")
    pm = QPixmap(64, 64)
    pm.fill(Qt.white)
    pm.save(img_path, "PNG")

    # Mock TaskManager to run on_finished immediately with mock OCR result
    class MockTaskManager:
        def submit(self, fn, type_, task_id, *args, on_finished=None, **kwargs):
            # Run synchronously for test
            result = fn(None, None, *args, **kwargs)
            if on_finished:
                on_finished(result)
            return "mock_task_id"

    # Mock database to return empty so it triggers the fallback to on-the-fly
    mock_db = MagicMock()
    mock_db.session.return_value.query.return_value.all.return_value = []

    panel = PreviewPanel(
        bus=MagicMock(),
        task_manager=MockTaskManager(),
        database=mock_db
    )
    panel.current_path = img_path
    panel._show_extracted_text_tab(img_path)

    # Since it is a blank white image, Tesseract OCR might return empty or filename fallback
    # The key thing is it should change the stack widget to extracted_text_area and show the content.
    assert panel.stack.currentWidget() is panel.extracted_text_area
    assert panel.extracted_text_content.text() != ""


def test_preview_extracted_text_copy(qapp):
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication

    panel = PreviewPanel(bus=MagicMock())
    panel.extracted_text_content.setText("Test clipboard copy")
    panel._copy_extracted_text()

    clipboard = QApplication.clipboard()
    assert clipboard.text() == "Test clipboard copy"


def test_preview_clean_image_ocr_text():
    # Only OCR
    t1 = "[OCR Text]\nHello world"
    assert PreviewPanel._clean_image_ocr_text(t1) == "Hello world"

    # OCR + Caption
    t2 = "[OCR Text]\nHello world\n\n[Image Caption]\nA description of the image"
    assert PreviewPanel._clean_image_ocr_text(t2) == "Hello world"

    # Only Caption
    t3 = "[Image Caption]\nA description of the image"
    assert PreviewPanel._clean_image_ocr_text(t3) == ""

    # Normal text
    t4 = "Hello world"
    assert PreviewPanel._clean_image_ocr_text(t4) == "Hello world"
