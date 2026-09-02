import logging

from core.logging_setup import setup_logging, get_logger, LOGGER_NAME


def test_setup_logging_returns_logger():
    logger = setup_logging(level=logging.DEBUG)
    assert isinstance(logger, logging.Logger)
    assert logger.name == LOGGER_NAME
    assert logger.handlers  # file + console


def test_get_logger_namespacing():
    child = get_logger("m1")
    assert child.name == f"{LOGGER_NAME}.m1"


def test_log_file_created(tmp_path):
    logger = setup_logging(log_dir=str(tmp_path))
    logger.info("hello from test")
    log_file = tmp_path / "intellivault.log"
    assert log_file.exists()
    assert "hello from test" in log_file.read_text(encoding="utf-8")
