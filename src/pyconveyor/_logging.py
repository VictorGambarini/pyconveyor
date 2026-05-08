"""Logging configuration helpers.

pyconveyor uses the standard ``logging`` module under the ``pyconveyor``
namespace.  Users configure verbosity through Python's normal logging API::

    import logging
    logging.getLogger("pyconveyor").setLevel(logging.DEBUG)

This module provides convenience helpers for common setups and implements the
one-time sensitive-content warning when DEBUG is enabled.
"""
from __future__ import annotations

import logging

_SENSITIVE_WARNING_FIRED = False
_SENTINEL_HANDLER_NAME = "pyconveyor_debug_sentinel"


class _SensitiveContentFilter(logging.Filter):
    """Fires a one-time WARNING when DEBUG logging is first enabled."""

    def filter(self, record: logging.LogRecord) -> bool:
        global _SENSITIVE_WARNING_FIRED
        if not _SENSITIVE_WARNING_FIRED:
            _SENSITIVE_WARNING_FIRED = True
            logger = logging.getLogger("pyconveyor")
            logger.warning(
                "pyconveyor DEBUG logging is enabled. "
                "Prompts and model responses will be logged verbatim — they may contain "
                "API keys, PII, or sensitive customer data. "
                "Keep logging at INFO or above in production."
            )
        return True


def configure_logging(
    level: int | str = logging.WARNING,
    format: str = "%(asctime)s %(name)s %(levelname)s  %(message)s",
    handler: logging.Handler | None = None,
) -> None:
    """Configure pyconveyor's root logger.

    Args:
        level: Log level (e.g. ``logging.INFO`` or ``"DEBUG"``).
        format: Log format string.
        handler: Custom handler.  Defaults to a ``StreamHandler``.
    """
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())

    pkg_logger = logging.getLogger("pyconveyor")
    pkg_logger.setLevel(level)

    if not pkg_logger.handlers:
        h = handler or logging.StreamHandler()
        h.setFormatter(logging.Formatter(format))
        pkg_logger.addHandler(h)

    if isinstance(level, int) and level <= logging.DEBUG:
        pkg_logger.addFilter(_SensitiveContentFilter())
