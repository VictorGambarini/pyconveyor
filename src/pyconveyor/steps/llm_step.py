"""LLM step execution with validation-feedback retry loop.

Implements §10 of the plan:
- parse + schema error unified feedback
- multi-turn conversation message structure (§10.2)
- retry_on, schema_strict, max_feedback_tokens, error_template
- smart conditional defaults (§10.4)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..errors import ParseError, SchemaValidationError
from ..llm import call_llm, extract_json
from ..prompt import render_prompt

if TYPE_CHECKING:
    from ..runner import RunContext

logger = logging.getLogger("pyconveyor.runner")

# ── Default error feedback templates ──────────────────────────────────────────

_DEFAULT_SCHEMA_FEEDBACK = """\
Your previous response failed schema validation. Here is what you returned:

{{ previous_output | truncate(max_feedback_tokens) }}

Validation errors:
{% for err in errors %}- {{ err.loc_str }}: {{ err.msg }}
{% endfor %}
Please fix these issues and return a corrected JSON object.
{% if retry_hint %}
{{ retry_hint }}
{% endif %}"""

_DEFAULT_PARSE_FEEDBACK = """\
Your previous response was not valid JSON:

{{ previous_output | truncate(max_feedback_tokens) }}

{{ parse_error_message }}

Please return only a valid JSON object, with no surrounding prose or markdown fences.
{% if retry_hint %}
{{ retry_hint }}
{% endif %}"""


@dataclass
class AttemptLog:
    """Record of one LLM call attempt."""

    step: str
    attempt: int  # 1-indexed
    status: str  # see §10.10
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    tokens: dict[str, int] | None = None
    raw_output: str | None = None
    error_type: str | None = None


@dataclass
class ErrorInfo:
    loc_str: str
    msg: str
    type: str


def _build_feedback(
    error_type: str,
    previous_output: str,
    errors: list[ErrorInfo],
    parse_error_message: str,
    attempt: int,
    retry_hint: str,
    max_feedback_tokens: int,
    error_template_path: str | None,
    pipeline_dir: Path,
) -> str:
    """Render the retry feedback message block."""

    def _truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n[…truncated for length…]"

    def _truncate_filter(text: str, length: int | None = None) -> str:
        return _truncate(text, length if length is not None else max_feedback_tokens)

    template_vars: dict[str, Any] = {
        "error_type": error_type,
        "previous_output": previous_output,
        "errors": errors,
        "parse_error_message": parse_error_message,
        "attempt": attempt,
        "retry_hint": retry_hint,
        "max_feedback_tokens": max_feedback_tokens,
    }

    if error_template_path:
        full_path = pipeline_dir / error_template_path
        from jinja2 import Environment, FileSystemLoader, StrictUndefined

        env = Environment(
            loader=FileSystemLoader(str(full_path.parent)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        env.filters["truncate"] = _truncate_filter  # type: ignore[assignment]
        tmpl = env.get_template(full_path.name)
        return tmpl.render(**template_vars)

    # Built-in templates
    from jinja2 import Environment, StrictUndefined

    env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    env.filters["truncate"] = _truncate_filter  # type: ignore[assignment]

    if error_type == "schema":
        return env.from_string(_DEFAULT_SCHEMA_FEEDBACK).render(**template_vars)
    return env.from_string(_DEFAULT_PARSE_FEEDBACK).render(**template_vars)


def execute_llm_step(
    step: dict[str, Any],
    resolved_inputs: dict[str, Any],
    client: Any,
    model_config: dict[str, Any],
    pipeline_dir: Path,
    rctx: RunContext,
    cache: Any | None = None,
    use_cache: bool = True,
    refresh_cache: bool = False,
    dry_run: bool = False,
) -> tuple[Any, list[AttemptLog]]:
    """Execute one LLM step and return ``(result, attempt_logs)``.

    Raises:
        ParseError / SchemaValidationError / Exception when max_attempts exhausted
        and should be handled by the runner.
    """
    name: str = step["name"]
    schema_cls = step.get("_schema_cls")
    parser_fn = step.get("_parser_fn")
    has_schema = schema_cls is not None

    # ── Defaults (§10.4) ──────────────────────────────────────────────────────
    max_attempts: int = step.get("max_attempts", 3 if has_schema else 1)
    error_feedback: bool = step.get("error_feedback", has_schema)
    retry_hint: str = step.get("retry_hint", "")
    schema_strict: bool = step.get("schema_strict", True)
    retry_on: list[str] = step.get("retry_on", ["parse", "schema"])
    max_feedback_tokens: int = step.get("max_feedback_tokens", 4000)
    error_template: str | None = step.get("error_template")

    logger.info(
        "Step '%s' (llm): model=%s max_attempts=%d error_feedback=%s",
        name,
        model_config.get("model", "?"),
        max_attempts,
        error_feedback,
    )

    # ── Build initial prompt ──────────────────────────────────────────────────
    prompt_path: str | None = step.get("prompt")
    system_path: str | None = step.get("system")

    # Merge resolved inputs into template context
    template_ctx = dict(resolved_inputs)

    if dry_run:
        log = AttemptLog(step=name, attempt=1, status="success", raw_output="[dry-run]")
        return None, [log]

    if prompt_path:
        full_prompt = str(pipeline_dir / prompt_path)
        rendered_prompt = render_prompt(
            Path(full_prompt).parent,
            Path(full_prompt).name,
            **template_ctx,
        )
    else:
        rendered_prompt = step.get("prompt_string", "")

    rendered_system: str | None = None
    if system_path:
        full_system = str(pipeline_dir / system_path)
        rendered_system = render_prompt(
            Path(full_system).parent,
            Path(full_system).name,
            **template_ctx,
        )

    # max_prompt_tokens guard
    max_prompt_tokens: int | None = step.get("max_prompt_tokens")
    if max_prompt_tokens is not None:
        # Simple char-based estimate (4 chars ≈ 1 token)
        est = len(rendered_prompt) // 4
        if est > max_prompt_tokens:
            from ..errors import PromptTooLargeError

            raise PromptTooLargeError(name, est, max_prompt_tokens)

    # ── Base messages (attempt 1) ─────────────────────────────────────────────
    base_messages: list[dict[str, str]] = []
    if rendered_system:
        base_messages.append({"role": "system", "content": rendered_system})
    base_messages.append({"role": "user", "content": rendered_prompt})

    # ── Extract model params ──────────────────────────────────────────────────
    model_name: str = model_config.get("model", "")
    provider: str = model_config.get("provider", "openai_compat")
    timeout: int = int(model_config.get("timeout", 120))
    temperature: float | None = step.get("temperature", model_config.get("temperature"))
    top_p: float | None = step.get("top_p", model_config.get("top_p"))
    max_tokens: int | None = step.get("max_tokens", model_config.get("max_tokens"))
    seed: int | None = step.get("seed", model_config.get("seed"))
    extra_params: dict[str, Any] = {
        **model_config.get("extra_params", {}),
        **step.get("extra_params", {}),
    }
    max_retries: int = int(model_config.get("max_retries", 2))
    retry_delay: float = float(model_config.get("retry_delay", 1.0))

    sampling_params: dict[str, Any] = {}
    if temperature is not None:
        sampling_params["temperature"] = temperature
    if top_p is not None:
        sampling_params["top_p"] = top_p
    if max_tokens is not None:
        sampling_params["max_tokens"] = max_tokens
    if seed is not None:
        sampling_params["seed"] = seed

    # ── Retry loop ────────────────────────────────────────────────────────────
    attempt_logs: list[AttemptLog] = []
    messages = list(base_messages)
    last_error: Exception | None = None
    result: Any = None

    for attempt_num in range(1, max_attempts + 1):
        log = AttemptLog(step=name, attempt=attempt_num, status="error")
        t0 = time.monotonic()

        # Cache lookup (only attempt 1, with original messages)
        cache_key_messages = list(base_messages)
        if cache is not None and use_cache and attempt_num == 1:
            cached = cache.get(provider, model_name, cache_key_messages, sampling_params)
            if cached is not None:
                raw = cached
                log.raw_output = raw
                rctx._cache_hits += 1
                logger.debug("Step '%s': cache hit", name)
            else:
                rctx._cache_misses += 1
                raw = _do_call(
                    client, messages, model_name, timeout, temperature, top_p,
                    max_tokens, seed, extra_params, max_retries, retry_delay
                )
                cache.set(provider, model_name, cache_key_messages, sampling_params, raw)
        else:
            if cache is not None and refresh_cache and attempt_num == 1:
                cache.invalidate(provider, model_name, cache_key_messages, sampling_params)
            raw, tokens = _do_call_with_usage(
                client, messages, model_name, timeout, temperature, top_p,
                max_tokens, seed, extra_params, max_retries, retry_delay
            )
            log.tokens = tokens
            if cache is not None and not refresh_cache:
                cache.set(provider, model_name, cache_key_messages, sampling_params, raw)

        log.raw_output = raw
        logger.debug("Step '%s' attempt %d raw response: %s", name, attempt_num, raw[:200])

        # ── Parse ──────────────────────────────────────────────────────────────
        try:
            if parser_fn is not None:
                parsed = parser_fn(raw)
            else:
                parsed = extract_json(raw)
        except Exception as e:
            log.elapsed_seconds = time.monotonic() - t0
            log.status = "parse_error"
            log.error_type = "parse"
            log.errors = [str(e)]
            attempt_logs.append(log)
            last_error = ParseError(str(e))

            if "parse" not in retry_on or attempt_num == max_attempts:
                break

            if error_feedback:
                feedback = _build_feedback(
                    "parse", raw, [], str(e), attempt_num + 1,
                    retry_hint, max_feedback_tokens, error_template, pipeline_dir
                )
                messages = list(base_messages) + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": feedback},
                ]
            continue

        # ── Schema validation ──────────────────────────────────────────────────
        if schema_cls is not None:
            try:
                result = schema_cls(**parsed) if isinstance(parsed, dict) else schema_cls.model_validate(parsed)
                log.elapsed_seconds = time.monotonic() - t0
                log.status = "success"
                attempt_logs.append(log)
                logger.info("Step '%s' succeeded on attempt %d", name, attempt_num)
                return result, attempt_logs
            except Exception as ve:
                error_infos = _pydantic_errors(ve)
                error_strs = [f"{e.loc_str}: {e.msg}" for e in error_infos]
                log.elapsed_seconds = time.monotonic() - t0
                log.status = "schema_error"
                log.error_type = "schema"
                log.errors = error_strs
                attempt_logs.append(log)
                last_error = SchemaValidationError(
                    f"Schema validation failed: {'; '.join(error_strs)}", ve
                )

                if schema_strict is False:
                    # Accept partial output
                    logger.warning(
                        "Step '%s': schema validation failed (schema_strict=false), "
                        "accepting parsed dict: %s",
                        name,
                        "; ".join(error_strs),
                    )
                    rctx._validation_warnings.append({
                        "step": name,
                        "attempt": attempt_num,
                        "errors": error_strs,
                    })
                    return parsed, attempt_logs

                if "schema" not in retry_on or attempt_num == max_attempts:
                    break

                if error_feedback:
                    feedback = _build_feedback(
                        "schema", raw, error_infos, "", attempt_num + 1,
                        retry_hint, max_feedback_tokens, error_template, pipeline_dir
                    )
                    messages = list(base_messages) + [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": feedback},
                    ]
                continue
        else:
            # No schema — return parsed directly
            log.elapsed_seconds = time.monotonic() - t0
            log.status = "success"
            attempt_logs.append(log)
            return parsed, attempt_logs

    # All attempts exhausted
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Step '{name}': no result after {max_attempts} attempts")


def _do_call(
    client: Any,
    messages: list[dict[str, str]],
    model: str,
    timeout: int,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    seed: int | None,
    extra_params: dict[str, Any],
    max_retries: int,
    retry_delay: float,
) -> str:
    text, _ = call_llm(
        client, messages, model, timeout=timeout,
        temperature=temperature, top_p=top_p, max_tokens=max_tokens, seed=seed,
        extra_params=extra_params, max_retries=max_retries, retry_delay=retry_delay,
    )
    return text


def _do_call_with_usage(
    client: Any,
    messages: list[dict[str, str]],
    model: str,
    timeout: int,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    seed: int | None,
    extra_params: dict[str, Any],
    max_retries: int,
    retry_delay: float,
) -> tuple[str, dict[str, int] | None]:
    return call_llm(
        client, messages, model, timeout=timeout,
        temperature=temperature, top_p=top_p, max_tokens=max_tokens, seed=seed,
        extra_params=extra_params, max_retries=max_retries, retry_delay=retry_delay,
    )


def _pydantic_errors(exc: Exception) -> list[ErrorInfo]:
    """Extract structured error info from a Pydantic ValidationError."""
    errors: list[ErrorInfo] = []
    try:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            for e in exc.errors():
                loc_parts = []
                for part in e.get("loc", ()):
                    loc_parts.append(f"[{part}]" if isinstance(part, int) else str(part))
                loc_str = ".".join(
                    p if not p.startswith("[") else p
                    for p in loc_parts
                ) if loc_parts else "?"
                errors.append(ErrorInfo(
                    loc_str=loc_str,
                    msg=e.get("msg", ""),
                    type=e.get("type", ""),
                ))
    except ImportError:
        errors.append(ErrorInfo(loc_str="?", msg=str(exc), type="unknown"))
    return errors
