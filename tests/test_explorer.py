import os

import pytest
from PySide6.QtCore import QElapsedTimer, Qt, QDir
from PySide6.QtWidgets import QApplication, QMessageBox

from app.container import Container
from ui.main_window import MainWindow
from widgets.file_explorer import FileExplorer


def _make_tree(tmp_path):
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.txt").write_text("bb")
    (tmp_path / "subdir").mkdir()
    return tmp_path


def _wait_model(ex, path, timeout=5000):
    """Spin the event loop until QFileSystemModel finishes loading a path."""
    timer = QElapsedTimer()
    timer.start()
    idx = ex.model.index(path)
    while ex.model.rowCount(idx) == 0 and timer.elapsed() < timeout:
        QApplication.processEvents()


def test_explorer_builds(qapp):
    FileExplorer()


def test_explorer_loads_directory(qapp, tmp_path):
    d = _make_tree(tmp_path)
    ex = FileExplorer()
    ex.set_path(str(d))
    assert ex.current_path == str(d)
    _wait_model(ex, str(d))
    rows = ex.model.rowCount(ex.model.index(str(d)))
    assert rows >= 3


def test_explorer_view_switch(qapp):
    ex = FileExplorer()
    ex.set_view("grid")
    assert ex.stack.currentIndex() == 1
    ex.set_view("list")
    assert ex.stack.currentIndex() == 0


def test_explorer_name_filter(qapp, tmp_path):
    d = _make_tree(tmp_path)
    ex = FileExplorer()
    ex.set_path(str(d))
    ex.set_name_filter("alpha")
    _wait_model(ex, str(d))
    idx = ex.model.index(str(d))
    # Non-matching rows are present but disabled (ItemIsEnabled cleared).
    enabled = [
        ex.model.fileName(ex.model.index(i, 0, idx))
        for i in range(ex.model.rowCount(idx))
        if ex.model.flags(ex.model.index(i, 0, idx)) & Qt.ItemIsEnabled
    ]
    assert enabled == ["alpha.txt"]


def test_explorer_clear_filter(qapp, tmp_path):
    d = _make_tree(tmp_path)
    ex = FileExplorer()
    ex.set_path(str(d))
    ex.set_name_filter("alpha")
    ex.set_name_filter("")
    _wait_model(ex, str(d))
    idx = ex.model.index(str(d))
    names = [ex.model.fileName(ex.model.index(i, 0, idx)) for i in range(ex.model.rowCount(idx))]
    assert "beta.txt" in names


def test_explorer_show_hidden(qapp):
    ex = FileExplorer()
    ex.set_show_hidden(True)
    assert ex.model.filter() & QDir.Hidden
    ex.set_show_hidden(False)
    assert not (ex.model.filter() & QDir.Hidden)


def test_main_window_explorer_wired(qapp, tmp_path):
    w = MainWindow(Container())
    d = _make_tree(tmp_path)
    w._navigate_to(str(d))
    # path_changed must have propagated to the explorer widget.
    assert w.explorer.current_path == str(d)


def test_file_activated_directory_navigates(qapp, tmp_path):
    d = _make_tree(tmp_path)
    w = MainWindow(Container())
    w._navigate_to(str(d))
    sub = str(d / "subdir")
    w._on_file_activated(sub)
    assert w.current_path == sub


def test_explorer_context_handlers_no_crash(qapp, monkeypatch, tmp_path):
    d = _make_tree(tmp_path)
    ex = FileExplorer()
    ex.set_path(str(d))
    QApplication.processEvents()
    target = str(d / "alpha.txt")
    # Stub blocking dialogs so the test never waits for user input.
    monkeypatch.setattr("widgets.file_explorer.QInputDialog.getText", lambda *a, **k: ("", False))
    monkeypatch.setattr("widgets.file_explorer.QMessageBox.information", lambda *a, **k: None)
    monkeypatch.setattr("widgets.file_explorer.QMessageBox.warning", lambda *a, **k: None)
    monkeypatch.setattr(
        "widgets.file_explorer.QMessageBox.question",
        lambda *a, **k: QMessageBox.Yes,
    )
    monkeypatch.setattr(
        "widgets.file_explorer.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(d),
    )
    ex._properties(target)   # should not raise
    ex._rename(target)       # cancels (empty) -> no-op
    ex._copy([target])       # copies into same dir (overwrites) -> no raise
    ex._delete([target])     # removes the file -> no raise
