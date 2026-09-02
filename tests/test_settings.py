import pytest
from PySide6.QtWidgets import QApplication

from core.config import Config
from app.signal_bus import SignalBus
from ui.theme_engine import ThemeEngine
from ui.settings_dialog import SettingsDialog
from database.engine import Database
from database.repository import Repository
from app.container import Container


def _settings(qapp, tmp_path):
    cfg = Config(path=str(tmp_path / "s.json"))
    bus = SignalBus()
    theme = ThemeEngine(cfg, bus)
    db = Database(str(tmp_path / "db.sqlite"))
    repo = Repository(db)
    dlg = SettingsDialog(cfg, bus, theme, repo)
    return cfg, bus, theme, repo, dlg


def test_settings_has_all_tabs(qapp, tmp_path):
    cfg, bus, theme, repo, dlg = _settings(qapp, tmp_path)
    names = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert "General" in names
    assert "Appearance" in names
    assert "File Explorer" in names
    assert "Database" in names
    assert "Plugins" in names
    assert "Performance" in names
    for reserved in ("AI", "OCR", "Models", "Embeddings", "LLM"):
        assert reserved in names


def test_reserved_tabs_present_but_disabled(qapp, tmp_path):
    from PySide6.QtWidgets import QLineEdit

    cfg, bus, theme, repo, dlg = _settings(qapp, tmp_path)
    names = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    idx = names.index("AI")
    tab = dlg.tabs.widget(idx)
    # The reserved tab contains disabled line edits (placeholder controls).
    edits = tab.findChildren(QLineEdit)
    assert edits
    assert all(not e.isEnabled() for e in edits)


def test_settings_apply_writes_config(qapp, tmp_path):
    cfg, bus, theme, repo, dlg = _settings(qapp, tmp_path)
    dlg.startup_path.setText("/tmp/intellivault")
    dlg.single_click.setChecked(True)
    dlg.max_threads.setValue(8)
    dlg.apply_settings()
    assert cfg.get("general.startup_path") == "/tmp/intellivault"
    assert cfg.get("general.single_click_open") is True
    assert cfg.get("performance.max_threads") == 8


def test_settings_theme_apply(qapp, tmp_path):
    cfg, bus, theme, repo, dlg = _settings(qapp, tmp_path)
    other = "light" if theme.current() == "dark" else "dark"
    dlg.theme_combo.setCurrentText(other)
    dlg.apply_settings()
    assert cfg.get("appearance.theme") == other
    # Theme engine applied a stylesheet to the running application.
    assert QApplication.instance().styleSheet() != ""


def test_settings_persist_to_db(qapp, tmp_path):
    cfg, bus, theme, repo, dlg = _settings(qapp, tmp_path)
    dlg.max_threads.setValue(7)
    dlg.apply_settings()
    assert repo.get_setting("performance.max_threads") == "7"


def test_main_window_opens_settings(qapp, tmp_path):
    from ui.main_window import MainWindow

    c = Container()
    w = MainWindow(c)
    dlg = SettingsDialog(c.config, c.bus, w.theme_engine, c.repository)
    dlg.max_threads.setValue(6)
    dlg.apply_settings()
    assert c.config.get("performance.max_threads") == 6
    w.deleteLater()
    c.shutdown()
