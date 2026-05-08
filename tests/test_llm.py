"""Tests for LLM utilities (make_client, call_llm, extract_json, probe_json_mode)."""
from __future__ import annotations

import pytest

from pyconveyor.llm import (
    _MockClient,
    call_llm,
    extract_json,
    make_client,
    register_provider,
)
from pyconveyor.errors import ParseError


# ── extract_json ──────────────────────────────────────────────────────────────

class TestExtractJson:
    def test_plain_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        result = extract_json('```json\n{"x": 2}\n```')
        assert result == {"x": 2}

    def test_fenced_no_lang(self):
        result = extract_json('```\n{"x": 3}\n```')
        assert result == {"x": 3}

    def test_json_in_prose(self):
        result = extract_json('Here is the result: {"ok": true} done.')
        assert result == {"ok": True}

    def test_json_array(self):
        assert extract_json("[1, 2, 3]") == [1, 2, 3]

    def test_bom_stripped(self):
        assert extract_json('\ufeff{"a": 1}') == {"a": 1}

    def test_whitespace(self):
        assert extract_json('  {"a": 1}  ') == {"a": 1}

    def test_invalid_raises(self):
        with pytest.raises(ParseError):
            extract_json("this is just text with no json")


# ── make_client ───────────────────────────────────────────────────────────────

class TestMakeClient:
    def test_mock_client(self):
        client = make_client("mock", responses=['{"ok": true}'])
        assert isinstance(client, _MockClient)

    def test_mock_client_sequence(self):
        client = make_client("mock", responses=["resp1", "resp2"])
        r1, _ = call_llm(client, [{"role": "user", "content": "hi"}], "mock")
        r2, _ = call_llm(client, [{"role": "user", "content": "hi"}], "mock")
        assert r1 == "resp1"
        assert r2 == "resp2"

    def test_mock_clamps_to_last(self):
        client = make_client("mock", responses=["only"])
        r1, _ = call_llm(client, [{"role": "user", "content": "hi"}], "mock")
        r2, _ = call_llm(client, [{"role": "user", "content": "hi"}], "mock")
        assert r1 == "only"
        assert r2 == "only"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            make_client("does_not_exist")

    def test_custom_provider_registration(self):
        sentinel = object()

        @register_provider("test_custom_provider_xyz")
        def _factory(**kwargs):
            return sentinel

        client = make_client("test_custom_provider_xyz")
        assert client is sentinel


# ── call_llm ─────────────────────────────────────────────────────────────────

class TestCallLlm:
    def test_returns_content(self):
        client = make_client("mock", responses=['{"x": 1}'])
        content, usage = call_llm(client, [{"role": "user", "content": "hi"}], "mock")
        assert content == '{"x": 1}'

    def test_usage_from_mock(self):
        client = make_client("mock")
        _, usage = call_llm(client, [{"role": "user", "content": "hi"}], "mock")
        # Mock usage is always 0; check structure
        if usage is not None:
            assert "prompt_tokens" in usage
            assert "completion_tokens" in usage
