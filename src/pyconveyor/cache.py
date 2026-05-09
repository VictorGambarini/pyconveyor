"""File-based response cache for development use.

**Never enable in production** — the cache stores model responses verbatim and
will silently serve stale data.  A one-time WARNING is emitted the first time a
cache hit occurs during a run.

Cache key = SHA-256 of (provider, model, messages JSON, sampling params JSON).
One file per key under the cache directory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("pyconveyor.cache")

_WARNED: set[str] = set()  # tracks which cache dirs have fired the production warning


def _cache_key(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    sampling: dict[str, Any],
) -> str:
    payload = json.dumps(
        {"provider": provider, "model": model, "messages": messages, "sampling": sampling},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class ResponseCache:
    """Disk-backed cache for LLM responses.

    Args:
        directory: Path to the cache directory.  Created if absent.
        ttl_days: Maximum age of cached entries in days.  ``None`` = no expiry.
    """

    def __init__(self, directory: str | Path = ".pyconveyor-cache", ttl_days: float | None = None) -> None:
        self._dir = Path(directory)
        self._ttl_seconds = ttl_days * 86400 if ttl_days is not None else None
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── public API ─────────────────────────────────────────────────────────────

    def get(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        sampling: dict[str, Any],
    ) -> str | None:
        """Return the cached response, or ``None`` on miss / expiry."""
        key = _cache_key(provider, model, messages, sampling)
        path = self._dir / key
        if not path.exists():
            return None
        if self._ttl_seconds is not None:
            age = time.time() - path.stat().st_mtime
            if age > self._ttl_seconds:
                path.unlink(missing_ok=True)
                return None

        # Emit a one-time production warning
        dir_str = str(self._dir)
        if dir_str not in _WARNED:
            _WARNED.add(dir_str)
            logger.warning(
                "pyconveyor cache hit in '%s'. "
                "Caching is for development only — disable before deploying to production.",
                self._dir,
            )
        logger.debug("Cache HIT key=%s", key[:16])
        return path.read_text(encoding="utf-8")

    def set(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        sampling: dict[str, Any],
        response: str,
    ) -> None:
        """Store *response* in the cache."""
        key = _cache_key(provider, model, messages, sampling)
        path = self._dir / key
        path.write_text(response, encoding="utf-8")
        logger.debug("Cache WRITE key=%s", key[:16])

    def invalidate(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        sampling: dict[str, Any],
    ) -> bool:
        """Delete a specific cache entry.  Returns True if the entry existed."""
        key = _cache_key(provider, model, messages, sampling)
        path = self._dir / key
        if path.exists():
            path.unlink()
            return True
        return False

    def clear(self) -> int:
        """Delete all entries in the cache directory.  Returns count deleted."""
        count = 0
        for f in self._dir.iterdir():
            if f.is_file():
                f.unlink()
                count += 1
        return count
