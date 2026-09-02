import pytest
from PySide6.QtWidgets import QApplication

from app.container import Container
from ui.main_window import MainWindow
from ui.theme_engine import ThemeEngine


def _window(qapp, container):
    return MainWindow(container)


def test_window_builds(qapp):
    container = Container()
    w = MainWindow(container)
    w.show()
    assert w.windowTitle().startswith("IntelliVault")
    assert w.menuBar() is not None
    assert w.toolbar is not None
    assert w.status is not None
    assert w.docks is not None


def test_theme_applied_on_startup(qapp):
    container = Container()
    w = MainWindow(container)
    app = QApplication.instance()
    assert app.styleSheet() != ""  # theme engine applied a stylesheet


def test_toggle_theme_changes_config(qapp):
    container = Container()
    w = MainWindow(container)
    before = container.config.get("appearance.theme")
    w.theme_engine.toggle()
    after = container.config.get("appearance.theme")
    assert before != after
    assert after in ("dark", "light")


def test_menu_toggle_docks(qapp):
    container = Container()
    w = MainWindow(container)
    w.docks.show_sidebar(True)
    w.menu.toggle_sidebar.emit()
    assert not w.docks.sidebar_dock.isVisible()
    w.menu.toggle_preview.emit()
    assert not w.docks.preview_dock.isVisible()


def test_status_bar_updates(qapp):
    container = Container()
    w = MainWindow(container)
    w.status.set_item_count(5)
    assert "5 items" in w.status.item_label.text()


def test_navigation_history_back_forward(qapp, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    w = MainWindow(Container())
    w._navigate_to(str(a))
    w._navigate_to(str(b))
    assert w.current_path == str(b)
    w._on_back()
    assert w.current_path == str(a)
    w._on_forward()
    assert w.current_path == str(b)


def test_navigation_history_drops_forward_on_new_nav(qapp, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    c = tmp_path / "c"
    a.mkdir()
    b.mkdir()
    c.mkdir()
    w = MainWindow(Container())
    w._navigate_to(str(a))
    w._navigate_to(str(b))
    w._on_back()  # now at a, forward history = [b]
    w._navigate_to(str(c))  # should discard forward history
    assert w.current_path == str(c)
    w._on_forward()  # nothing forward -> stays at c
    assert w.current_path == str(c)

