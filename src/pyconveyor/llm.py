"""LLM client factory and utilities.

Standalone utilities — usable without the pipeline runner:

    from pyconveyor.llm import make_client, call_llm, probe_json_mode, extract_json
    from pyconveyor import register_provider
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

from .errors import ParseError

logger = logging.getLogger("pyconveyor.llm")

# ── Provider registry ──────────────────────────────────────────────────────────

_PROVIDER_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_provider(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register a custom LLM provider factory.

    The factory receives ``base_url``, ``api_key``, and any extra kwargs
    passed to ``make_client``.  It must return a client with an OpenAI-style
    ``client.chat.completions.create(**kwargs)`` interface.

    Example::

        from pyconveyor import register_provider

        @register_provider("my_backend")
        def make_my_client(base_url, api_key, **kwargs):
            return MyClient(base_url, api_key)
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _PROVIDER_REGISTRY[name] = fn
        return fn

    return decorator


# ── Client factory ─────────────────────────────────────────────────────────────

def make_client(
    provider: str = "openai_compat",
    base_url: str | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> Any:
    """Create an LLM client for *provider*.

    Supported providers:
    - ``openai_compat`` (default) — ``openai.OpenAI``; works with Ollama, vLLM,
      LM Studio, and any OpenAI-compatible proxy.
    - ``anthropic`` — ``anthropic.Anthropic`` native SDK
      (requires ``pip install pyconveyor[anthropic]``).
    - ``mock`` — returns a ``_MockClient`` for tests without API calls.
    - Any name registered with ``@register_provider``.

    Raises:
        ValueError: Unknown provider.
        ImportError: anthropic extra not installed.
    """
    if provider in _PROVIDER_REGISTRY:
        return _PROVIDER_REGISTRY[provider](base_url=base_url, api_key=api_key, **kwargs)

    if provider == "openai_compat":
        from openai import OpenAI

        client_kwargs: dict[str, Any] = {}
        if base_url:
            client_kwargs["base_url"] = base_url
        if api_key:
            client_kwargs["api_key"] = api_key
        return OpenAI(**client_kwargs)

    if provider == "anthropic":
        try:
            from anthropic import Anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is not installed. "
                "Run: pip install pyconveyor[anthropic]"
            ) from exc
        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        return _AnthropicWrapper(Anthropic(**client_kwargs))

    if provider == "mock":
        return _MockClient(**kwargs)

    raise ValueError(
        f"Unknown provider '{provider}'. "
        f"Registered providers: openai_compat, anthropic, mock"
        + (f", {', '.join(_PROVIDER_REGISTRY)}" if _PROVIDER_REGISTRY else "")
        + ". Use @register_provider to add custom providers."
    )


# ── JSON extraction ────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL | re.IGNORECASE)
_JSON_RE = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


def extract_json(text: str) -> Any:
    """Extract and parse a JSON value from *text*.

    Handles:
    - Fenced code blocks (```json ... ```)
    - Prose surrounding a JSON object / array
    - BOM and leading/trailing whitespace

    Raises:
        ParseError: No valid JSON found.
    """
    text = text.strip().lstrip("\ufeff")

    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip fenced code block
    fence = _FENCE_RE.search(text)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. First JSON-shaped blob in prose
    for m in _JSON_RE.finditer(text):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue

    raise ParseError(
        f"Could not extract valid JSON from response: {text[:300]!r}"
    )


# ── JSON mode probe ────────────────────────────────────────────────────────────

def probe_json_mode(
    client: Any,
    model: str,
    timeout: int = 30,
) -> bool:
    """Return True if the endpoint accepts ``response_format={"type":"json_object"}``."""
    try:
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": 'Return {"ok": true}'}],
            response_format={"type": "json_object"},
            max_tokens=10,
            timeout=timeout,
        )
        return True
    except Exception as e:
        logger.debug("JSON mode probe failed for model '%s': %s", model, e)
        return False


# ── LLM call with retries ──────────────────────────────────────────────────────

def call_llm(
    client: Any,
    messages: list[dict[str, str]],
    model: str,
    timeout: int = 120,
    json_mode: bool = False,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    seed: int | None = None,
    extra_params: dict[str, Any] | None = None,
    max_retries: int = 2,
    retry_delay: float = 1.0,
) -> tuple[str, dict[str, int] | None]:
    """Call an LLM and return ``(raw_text, usage_dict)``.

    Handles HTTP-level 429 / 5xx retries with exponential backoff.
    4xx errors (except 429) are not retried.

    Returns:
        A ``(content, usage)`` tuple where *usage* may be ``None`` if the provider
        does not expose token counts.  When present, *usage* has keys
        ``"prompt_tokens"``, ``"completion_tokens"``, ``"total_tokens"``.
    """
    if isinstance(client, _AnthropicWrapper):
        return _call_anthropic(client, messages, model, timeout, temperature, top_p, max_tokens, extra_params, max_retries, retry_delay)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "timeout": timeout,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if top_p is not None:
        kwargs["top_p"] = top_p
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if seed is not None:
        kwargs["seed"] = seed
    if extra_params:
        kwargs.update(extra_params)

    last_error: Exception = RuntimeError("No attempts made")
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(**kwargs)
            content: str = response.choices[0].message.content or ""
            usage: dict[str, int] | None = None
            raw_usage = getattr(response, "usage", None)
            if raw_usage is not None:
                usage = {
                    "prompt_tokens": getattr(raw_usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(raw_usage, "completion_tokens", 0),
                    "total_tokens": getattr(raw_usage, "total_tokens", 0),
                }
                logger.info(
                    "LLM call: model=%s tokens=%d", model, usage["total_tokens"]
                )
            return content, usage
        except Exception as e:
            last_error = e
            status_code = getattr(e, "status_code", None)
            # Don't retry on 4xx other than 429
            if status_code is not None and 400 <= status_code < 500 and status_code != 429:
                raise
            if attempt < max_retries:
                delay = retry_delay * (2**attempt)
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    e,
                )
                time.sleep(delay)

    raise last_error


def _call_anthropic(
    client: _AnthropicWrapper,
    messages: list[dict[str, str]],
    model: str,
    timeout: int,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    extra_params: dict[str, Any] | None,
    max_retries: int,
    retry_delay: float,
) -> tuple[str, dict[str, int] | None]:
    system_parts: list[str] = []
    user_messages: list[dict[str, str]] = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
        else:
            user_messages.append(msg)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": user_messages,
        "max_tokens": max_tokens or 4096,
    }
    if system_parts:
        kwargs["system"] = "\n".join(system_parts)
    if temperature is not None:
        kwargs["temperature"] = temperature
    if top_p is not None:
        kwargs["top_p"] = top_p
    if timeout:
        kwargs["timeout"] = timeout
    if extra_params:
        kwargs.update(extra_params)

    last_error: Exception = RuntimeError("No attempts made")
    for attempt in range(max_retries + 1):
        try:
            response = client._client.messages.create(**kwargs)
            content = response.content[0].text
            input_tokens = getattr(response.usage, "input_tokens", 0)
            output_tokens = getattr(response.usage, "output_tokens", 0)
            usage: dict[str, int] = {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            }
            return content, usage
        except Exception as e:
            last_error = e
            status_code = getattr(e, "status_code", None)
            if status_code is not None and 400 <= status_code < 500 and status_code != 429:
                raise
            if attempt < max_retries:
                delay = retry_delay * (2**attempt)
                logger.warning(
                    "Anthropic call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    e,
                )
                time.sleep(delay)

    raise last_error


# ── Provider client wrappers ───────────────────────────────────────────────────

class _AnthropicWrapper:
    """Thin wrapper so ``isinstance(client, _AnthropicWrapper)`` dispatches correctly."""

    def __init__(self, client: Any) -> None:
        self._client = client


class _MockClient:
    """Mock client for unit tests.  Returns a configured sequence of responses."""

    def __init__(
        self,
        responses: list[str] | str | None = None,
        **kwargs: Any,
    ) -> None:
        if responses is None:
            responses = ['{"result": "mock"}']
        if isinstance(responses, str):
            responses = [responses]
        self._responses: list[str] = list(responses)
        self._call_count = 0

    @property
    def chat(self) -> _MockChatNamespace:
        return _MockChatNamespace(self)

    def _next_response(self) -> str:
        idx = min(self._call_count, len(self._responses) - 1)
        text = self._responses[idx]
        self._call_count += 1
        return text


class _MockChatNamespace:
    def __init__(self, client: _MockClient) -> None:
        self._client = client

    @property
    def completions(self) -> _MockCompletions:
        return _MockCompletions(self._client)


class _MockCompletions:
    def __init__(self, client: _MockClient) -> None:
        self._client = client

    def create(self, **kwargs: Any) -> _MockResponse:
        return _MockResponse(self._client._next_response())


class _MockResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_MockChoice(content)]
        self.usage = _MockUsage()


class _MockChoice:
    def __init__(self, content: str) -> None:
        self.message = _MockMessage(content)
        self.finish_reason = "stop"


class _MockMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _MockUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
