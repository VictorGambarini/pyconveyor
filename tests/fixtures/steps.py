"""Step functions used by fixture pipelines."""
from __future__ import annotations

from typing import Any


def identity(**kwargs: Any) -> Any:
    """Return the first argument value unchanged."""
    if len(kwargs) == 1:
        return next(iter(kwargs.values()))
    return kwargs


_failure_log: list[tuple[str, Exception]] = []


def record_failure(step_name: str, exc: Exception, rctx: Any) -> None:
    """on_failure callback — records the failure in module-level log."""
    _failure_log.append((step_name, exc))
