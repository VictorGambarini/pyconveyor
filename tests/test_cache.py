"""Tests for the file-based response cache."""
from __future__ import annotations

import time

from pyconveyor.cache import ResponseCache, _cache_key


class TestCacheKey:
    def test_same_inputs_same_key(self) -> None:
        k1 = _cache_key("openai", "gpt-4", [{"role": "user", "content": "hi"}], {"temperature": 0.5})
        k2 = _cache_key("openai", "gpt-4", [{"role": "user", "content": "hi"}], {"temperature": 0.5})
        assert k1 == k2

    def test_different_provider_different_key(self) -> None:
        k1 = _cache_key("openai", "gpt-4", [], {})
        k2 = _cache_key("anthropic", "gpt-4", [], {})
        assert k1 != k2

    def test_different_messages_different_key(self) -> None:
        k1 = _cache_key("openai", "m", [{"role": "user", "content": "a"}], {})
        k2 = _cache_key("openai", "m", [{"role": "user", "content": "b"}], {})
        assert k1 != k2

    def test_sampling_params_affect_key(self) -> None:
        k1 = _cache_key("openai", "m", [], {"temperature": 0.5})
        k2 = _cache_key("openai", "m", [], {"temperature": 0.9})
        assert k1 != k2

    def test_returns_hex_string(self) -> None:
        k = _cache_key("openai", "m", [], {})
        assert len(k) == 64
        int(k, 16)  # should not raise


class TestResponseCache:
    MSGS = [{"role": "user", "content": "hello"}]
    PARAMS: dict = {}

    def test_miss_returns_none(self, tmp_path) -> None:
        cache = ResponseCache(tmp_path / "cache")
        result = cache.get("openai", "gpt-4", self.MSGS, self.PARAMS)
        assert result is None

    def test_set_then_get(self, tmp_path) -> None:
        cache = ResponseCache(tmp_path / "cache")
        cache.set("openai", "gpt-4", self.MSGS, self.PARAMS, '{"answer": 42}')
        result = cache.get("openai", "gpt-4", self.MSGS, self.PARAMS)
        assert result == '{"answer": 42}'

    def test_set_overwrites(self, tmp_path) -> None:
        cache = ResponseCache(tmp_path / "cache")
        cache.set("openai", "m", self.MSGS, self.PARAMS, "first")
        cache.set("openai", "m", self.MSGS, self.PARAMS, "second")
        assert cache.get("openai", "m", self.MSGS, self.PARAMS) == "second"

    def test_invalidate_removes_entry(self, tmp_path) -> None:
        cache = ResponseCache(tmp_path / "cache")
        cache.set("openai", "m", self.MSGS, self.PARAMS, "hi")
        removed = cache.invalidate("openai", "m", self.MSGS, self.PARAMS)
        assert removed is True
        assert cache.get("openai", "m", self.MSGS, self.PARAMS) is None

    def test_invalidate_missing_returns_false(self, tmp_path) -> None:
        cache = ResponseCache(tmp_path / "cache")
        assert cache.invalidate("openai", "m", self.MSGS, self.PARAMS) is False

    def test_clear_returns_count(self, tmp_path) -> None:
        cache = ResponseCache(tmp_path / "cache")
        cache.set("openai", "m", self.MSGS, self.PARAMS, "a")
        cache.set("openai", "m2", self.MSGS, self.PARAMS, "b")
        count = cache.clear()
        assert count == 2

    def test_clear_empty_cache_returns_zero(self, tmp_path) -> None:
        cache = ResponseCache(tmp_path / "cache")
        assert cache.clear() == 0

    def test_ttl_expiry(self, tmp_path) -> None:
        cache = ResponseCache(tmp_path / "cache", ttl_days=1 / 86400)  # 1-second TTL
        cache.set("openai", "m", self.MSGS, self.PARAMS, "data")
        # Backdate the file to force expiry
        key_file = next((tmp_path / "cache").iterdir())
        import os
        old_time = time.time() - 5  # 5 seconds ago
        os.utime(key_file, (old_time, old_time))
        result = cache.get("openai", "m", self.MSGS, self.PARAMS)
        assert result is None

    def test_no_ttl_does_not_expire(self, tmp_path) -> None:
        cache = ResponseCache(tmp_path / "cache", ttl_days=None)
        cache.set("openai", "m", self.MSGS, self.PARAMS, "data")
        result = cache.get("openai", "m", self.MSGS, self.PARAMS)
        assert result == "data"

    def test_creates_directory(self, tmp_path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        ResponseCache(nested)
        assert nested.exists()
