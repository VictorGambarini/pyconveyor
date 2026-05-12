"""HTTP step executor."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("pyconveyor.http")

_REDACTED_HEADERS = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "cookie",
    "set-cookie",
}


def execute_http_step(
    step: dict[str, Any],
    resolved_request: dict[str, Any],
    dry_run: bool = False,
) -> Any:
    """Execute an HTTP request and return parsed output."""
    if dry_run:
        return None

    method = str(resolved_request.get("method", "GET")).upper()
    url = str(resolved_request.get("url", ""))
    headers = _to_str_dict(resolved_request.get("headers"))
    params = _to_str_dict(resolved_request.get("params"))
    body = resolved_request.get("body")

    timeout_seconds = float(step.get("timeout_seconds", 30))
    retries = int(step.get("retries", 2))
    backoff = float(step.get("backoff_seconds", 0.5))
    expected_status = step.get("expected_status")
    response_format = step.get("response_format", "json")

    allowed_status = set(expected_status) if isinstance(expected_status, list) else None

    attempts = retries + 1
    last_exc: Exception | None = None

    for attempt in range(attempts):
        try:
            response = httpx.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=body,
                timeout=timeout_seconds,
            )
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff * (2**attempt))
                continue
            raise RuntimeError(f"HTTP step '{step['name']}' request failed: {exc}") from exc

        if _is_expected_status(response.status_code, allowed_status):
            return _format_response(response, response_format, step["name"])

        if 500 <= response.status_code <= 599 and attempt < retries:
            time.sleep(backoff * (2**attempt))
            continue

        redacted = _redact_headers(headers)
        snippet = response.text[:500]
        raise RuntimeError(
            f"HTTP step '{step['name']}' failed: status={response.status_code} "
            f"method={method} url={url} headers={redacted} body={snippet!r}"
        )

    if last_exc is not None:
        raise RuntimeError(f"HTTP step '{step['name']}' request failed: {last_exc}") from last_exc
    raise RuntimeError(f"HTTP step '{step['name']}' failed")


def _is_expected_status(status_code: int, allowed_status: set[int] | None) -> bool:
    if allowed_status is not None:
        return status_code in allowed_status
    return 200 <= status_code <= 299


def _format_response(response: httpx.Response, response_format: str, step_name: str) -> Any:
    if response_format == "raw":
        return response.text
    if response_format == "full":
        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": _parse_json_body(response, step_name, fallback_to_text=True),
        }
    return _parse_json_body(response, step_name, fallback_to_text=False)


def _parse_json_body(response: httpx.Response, step_name: str, fallback_to_text: bool) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        if fallback_to_text:
            return response.text
        raise RuntimeError(
            f"HTTP step '{step_name}' expected JSON response but failed to parse body: {exc}"
        ) from exc


def _to_str_dict(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(f"HTTP headers/params must be mappings, got {type(value).__name__}")
    return {str(k): str(v) for k, v in value.items() if v is not None}


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in _REDACTED_HEADERS:
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = value
    return redacted
