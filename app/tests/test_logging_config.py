import importlib
import logging


def _reload_with_level(monkeypatch, level: str):
    monkeypatch.setenv("LOG_LEVEL", level)
    import src.config as cfg

    importlib.reload(cfg)
    import src.logging_config as lc

    importlib.reload(lc)
    return lc


def test_configure_logging_applies_level(monkeypatch):
    lc = _reload_with_level(monkeypatch, "DEBUG")
    lc.configure_logging()
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_invalid_level_falls_back_to_info(monkeypatch):
    lc = _reload_with_level(monkeypatch, "NOPE")
    lc.configure_logging()
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_pins_noisy_libraries_to_warning(monkeypatch):
    lc = _reload_with_level(monkeypatch, "DEBUG")
    lc.configure_logging()
    for name in ("botocore", "boto3", "urllib3", "s3transfer"):
        assert logging.getLogger(name).level == logging.WARNING
