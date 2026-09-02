import os

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from app.container import Container
from ui.main_window import MainWindow
from widgets.folder_tree import FolderTree
from widgets.favorites import FavoritesWidget
from widgets.drives import DrivesWidget
from widgets.breadcrumb import Breadcrumb


def test_navigation_widgets_build(qapp):
    FolderTree()
    DrivesWidget()
    Breadcrumb()
    FavoritesWidget(Container().config)


def test_folder_tree_emits_on_navigate(qapp, tmp_path):
    tree = FolderTree()
    received = []
    tree.folder_selected.connect(received.append)
    idx = tree._model.index(str(tmp_path))
    tree._on_clicked(idx)
    assert received and received[0] == str(tmp_path)


def test_drives_lists_root(qapp):
    drives = DrivesWidget()
    texts = [drives.list.item(i).text() for i in range(drives.list.count())]
    assert "/" in texts


def test_favorites_add_remove(qapp, tmp_path):
    cfg = Container().config
    cfg.set("favorites.paths", [])
    fav = FavoritesWidget(cfg)
    fav.set_current_path(str(tmp_path))
    fav._add_current()
    assert str(tmp_path) in fav._paths()
    # add a fake item and select+remove it
    fav._add_item("/tmp/xyz")
    fav.list.setCurrentRow(fav.list.count() - 1)
    fav._remove_selected()
    assert "/tmp/xyz" not in fav._paths()


def test_breadcrumb_renders_segments(qapp):
    bc = Breadcrumb()
    bc.set_path("/home/user/docs")
    labels = [
        bc.hbox.itemAt(i).widget().text()
        for i in range(bc.hbox.count())
        if isinstance(bc.hbox.itemAt(i).widget(), QPushButton)
    ]
    assert labels == ["/", "home", "user", "docs"]


def test_main_window_navigation_updates_path(qapp):
    w = MainWindow(Container())
    target = os.path.expanduser("~")
    w._navigate_to(target)
    assert w.current_path == target
    assert w.breadcrumb.edit.text() == target
    assert w.status.space_label.text().startswith("Free:")


def test_main_window_up_goes_to_parent(qapp):
    w = MainWindow(Container())
    child = os.path.expanduser("~/Documents") if os.path.isdir(
        os.path.expanduser("~/Documents")
    ) else os.path.expanduser("~")
    w._navigate_to(child)
    w._on_up()
    assert w.current_path == os.path.dirname(child)
