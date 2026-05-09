"""Tests for _logging.py — configure_logging and sensitive-content filter."""
from __future__ import annotations

import logging

import pytest

import pyconveyor._logging as _log_mod
from pyconveyor._logging import configure_logging


@pytest.fixture(autouse=True)
def _reset_logging():
    """Reset pyconveyor logger and module globals before each test."""
    logger = logging.getLogger("pyconveyor")
    # Remove all handlers added by configure_logging
    for h in logger.handlers[:]:
        logger.removeHandler(h)
    logger.setLevel(logging.WARNING)

    # Reset the one-time warning flag and remove any added filters
    _log_mod._SENSITIVE_WARNING_FIRED = False
    for f in logger.filters[:]:
        logger.removeFilter(f)

    yield

    # Clean up after test
    for h in logger.handlers[:]:
        logger.removeHandler(h)
    logger.setLevel(logging.WARNING)
    _log_mod._SENSITIVE_WARNING_FIRED = False
    for f in logger.filters[:]:
        logger.removeFilter(f)


class TestConfigureLogging:
    def test_sets_log_level_int(self):
        configure_logging(level=logging.INFO)
        logger = logging.getLogger("pyconveyor")
        assert logger.level == logging.INFO

    def test_sets_log_level_string(self):
        configure_logging(level="INFO")
        logger = logging.getLogger("pyconveyor")
        assert logger.level == logging.INFO

    def test_adds_stream_handler_by_default(self):
        configure_logging()
        logger = logging.getLogger("pyconveyor")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_custom_handler_used(self):
        custom = logging.NullHandler()
        configure_logging(handler=custom)
        logger = logging.getLogger("pyconveyor")
        assert custom in logger.handlers

    def test_second_call_does_not_add_duplicate_handler(self):
        configure_logging()
        configure_logging()
        logger = logging.getLogger("pyconveyor")
        # Second call skips addHandler since handlers already exist
        assert len(logger.handlers) == 1

    def test_debug_level_adds_sensitive_filter(self):
        configure_logging(level=logging.DEBUG)
        logger = logging.getLogger("pyconveyor")
        from pyconveyor._logging import _SensitiveContentFilter
        assert any(isinstance(f, _SensitiveContentFilter) for f in logger.filters)

    def test_info_level_no_sensitive_filter(self):
        configure_logging(level=logging.INFO)
        logger = logging.getLogger("pyconveyor")
        from pyconveyor._logging import _SensitiveContentFilter
        assert not any(isinstance(f, _SensitiveContentFilter) for f in logger.filters)


class TestSensitiveContentFilter:
    def test_filter_fires_warning_once(self):
        """First DEBUG log record triggers a one-time WARNING."""
        configure_logging(level=logging.DEBUG)
        logger = logging.getLogger("pyconveyor")

        records: list[logging.LogRecord] = []
        handler = logging.handlers_collector(records) if hasattr(logging, "handlers_collector") else None

        # Use a custom handler to capture records
        captured: list[logging.LogRecord] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        cap = CapturingHandler()
        cap.setLevel(logging.DEBUG)
        logger.addHandler(cap)

        # Fire a debug record — should trigger the one-time WARNING first
        logger.debug("test debug message")

        # The WARNING should appear in captured records
        warning_records = [r for r in captured if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1
        assert "sensitive" in warning_records[0].message.lower() or "debug" in warning_records[0].message.lower()

    def test_filter_fires_warning_only_once(self):
        """Multiple debug records still only fire the warning once."""
        configure_logging(level=logging.DEBUG)
        logger = logging.getLogger("pyconveyor")

        captured: list[logging.LogRecord] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        cap = CapturingHandler()
        cap.setLevel(logging.DEBUG)
        logger.addHandler(cap)

        logger.debug("first")
        logger.debug("second")
        logger.debug("third")

        warning_records = [r for r in captured if r.levelno == logging.WARNING]
        assert len(warning_records) == 1

    def test_filter_returns_true(self):
        """Filter must return True so the original record is still processed."""
        from pyconveyor._logging import _SensitiveContentFilter

        _log_mod._SENSITIVE_WARNING_FIRED = True  # suppress the side effect
        f = _SensitiveContentFilter()
        record = logging.LogRecord(
            name="pyconveyor", level=logging.DEBUG,
            pathname="", lineno=0, msg="test", args=(), exc_info=None,
        )
        assert f.filter(record) is True
