"""Internal utilities: dynamic import, string-distance suggestions, env-var expansion."""
from __future__ import annotations

import importlib
import os
import re
from collections.abc import Callable
from difflib import get_close_matches
from typing import Any

from .errors import CallableImportError

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def expand_env_vars(value: Any) -> Any:
    """Recursively expand ``${VAR_NAME}`` in YAML string values using ``os.environ``."""
    if isinstance(value, str):
        def _replace(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), m.group(0))  # leave unexpanded if missing

        return _ENV_VAR_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(v) for v in value]
    return value


def import_callable(
    dotted: str,
    file: str | None = None,
    key_path: str | None = None,
) -> Callable[..., Any]:
    """Import a callable from ``'module.sub:function'`` notation.

    Raises ``CallableImportError`` with a "did you mean?" suggestion when the
    module exists but the attribute is not found.
    """
    if ":" not in dotted:
        raise CallableImportError(
            f"Expected 'module:callable' notation, got {dotted!r}",
            file=file,
            key_path=key_path,
        )
    module_path, attr = dotted.rsplit(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise CallableImportError(
            f"Cannot import module '{module_path}': {e}",
            file=file,
            key_path=key_path,
        ) from e
    if not hasattr(module, attr):
        # Build "did you mean?" from public names in the module
        candidates = [n for n in dir(module) if not n.startswith("_")]
        suggestion = suggest(attr, candidates)
        raise CallableImportError(
            f"Module '{module_path}' has no attribute '{attr}'",
            file=file,
            key_path=key_path,
            suggestion=f"{module_path}:{suggestion}" if suggestion else None,
        )
    from typing import cast
    return cast("Callable[..., Any]", getattr(module, attr))


def suggest(target: str, candidates: list[str], cutoff: float = 0.6) -> str | None:
    """Return the closest matching candidate, or None."""
    matches = get_close_matches(target, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None
