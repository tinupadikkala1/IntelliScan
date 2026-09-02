import os
import tempfile

from core.config import Config, DEFAULTS


def _new_config() -> Config:
    return Config(path=os.path.join(tempfile.mkdtemp(), "settings.json"))


def test_defaults_loaded():
    cfg = _new_config()
    assert cfg.get("appearance.theme") == DEFAULTS["appearance"]["theme"]
    assert cfg.get("explorer.default_view") == "list"


def test_get_missing_returns_default():
    cfg = _new_config()
    assert cfg.get("does.not.exist", "fallback") == "fallback"


def test_set_and_get():
    cfg = _new_config()
    cfg.set("general.startup_path", "/tmp", save=False)
    assert cfg.get("general.startup_path") == "/tmp"


def test_deep_update_preserves_other_keys():
    cfg = _new_config()
    cfg.set("explorer.default_view", "grid")
    # Reload from the same file to verify persistence + merge.
    cfg2 = Config(path=cfg.path)
    assert cfg2.get("explorer.default_view") == "grid"
    # Unrelated default keys must survive.
    assert cfg2.get("appearance.theme") == DEFAULTS["appearance"]["theme"]


def test_change_signal_emitted():
    cfg = _new_config()
    fired = []
    cfg.changed.connect(lambda k: fired.append(k))
    cfg.set("performance.max_threads", 8)
    assert "performance.max_threads" in fired
