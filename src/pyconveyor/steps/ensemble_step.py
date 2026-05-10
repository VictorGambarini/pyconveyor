"""Ensemble step: run N LLM members in parallel, optionally judge and merge results."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runner import RunContext
    from ..steps.llm_step import AttemptLog

logger = logging.getLogger("pyconveyor.runner")

# Built-in judge prompt suffix — appended to the rendered member prompt when
# judge.prompt is not specified. Receives: members (list of {name,model,output}),
# schema_hint (str).
_DEFAULT_JUDGE_SUFFIX = """\


---
The above prompt was independently sent to {{ members | length }} model(s). \
Here are their outputs:

{% for m in members %}
### {{ m.name }}
```json
{{ m.output }}
```
{% endfor %}

Your task: Review all outputs carefully. Identify any conflicts, errors, or omissions.
Return a single merged JSON result that best represents the correct answer, \
following the same schema.
{% if schema_hint %}
Schema:
{{ schema_hint }}
{% endif %}"""


def execute_ensemble_step(
    step: dict[str, Any],
    rctx: RunContext,
    execute_member: Callable[..., tuple[Any, list[AttemptLog]]],
    pipeline_dir: Path,
    use_cache: bool = True,
    refresh_cache: bool = False,
    dry_run: bool = False,
) -> tuple[Any, list[AttemptLog]]:
    """Execute an ensemble step.

    Runs member LLM calls in parallel. If a judge is configured and its
    condition is met, runs the judge to merge results. Falls back to the best
    available member result if the judge is skipped or fails.

    Args:
        step: Ensemble step spec (pre-validated, ``_schema_cls`` injected).
        rctx: Current run context.
        execute_member: ``(step_spec, rctx, *, use_cache, refresh_cache, dry_run)
            → (value, logs)`` — executes one synthetic LLM step.
        pipeline_dir: Pipeline file's directory (for prompt path resolution).
        use_cache: Passed through to member and judge calls.
        refresh_cache: Passed through to member and judge calls.
        dry_run: Passed through to member and judge calls.

    Returns:
        ``(winning_value, all_attempt_logs)``
    """
    from ..runner import StepResult
    from ..steps.llm_step import AttemptLog

    ensemble_name: str = step["name"]
    step_prompt: str | None = step.get("prompt")
    step_schema_cls: Any = step.get("_schema_cls")
    members_spec: list[dict[str, Any]] = step.get("members", [])
    judge_spec: dict[str, Any] | None = step.get("judge")

    # ── Build synthetic LLM step specs for each member ────────────────────────
    member_steps: list[tuple[str, str, dict[str, Any], bool]] = []
    for m in members_spec:
        model_key: str = m.get("model", "")
        member_name: str = m.get("name", model_key)
        required: bool = m.get("required", True)

        member_step: dict[str, Any] = {
            "name": f"{ensemble_name}.{member_name}",
            "type": "llm",
            "model": model_key,
        }
        # Inherit prompt from ensemble level unless the member overrides it
        if "prompt" in m:
            member_step["prompt"] = m["prompt"]
        elif step_prompt:
            member_step["prompt"] = step_prompt

        if step_schema_cls is not None:
            member_step["_schema_cls"] = step_schema_cls

        # Forward per-member LLM tuning fields
        for k in (
            "temperature",
            "top_p",
            "max_tokens",
            "seed",
            "max_attempts",
            "error_feedback",
            "retry_hint",
            "vars",
            "system",
            "schema_strict",
            "retry_on",
            "max_feedback_tokens",
        ):
            if k in m:
                member_step[k] = m[k]

        member_steps.append((member_name, model_key, member_step, required))

    # ── Run members in parallel ────────────────────────────────────────────────
    all_logs: list[AttemptLog] = []
    member_results: dict[str, Any] = {}
    required_errors: dict[str, Exception] = {}

    with ThreadPoolExecutor(max_workers=len(member_steps) or 1) as pool:
        future_to_info = {
            pool.submit(
                execute_member,
                ms,
                rctx,
                use_cache=use_cache,
                refresh_cache=refresh_cache,
                dry_run=dry_run,
            ): (mn, req)
            for mn, _mk, ms, req in member_steps
        }
        for future in as_completed(future_to_info):
            member_name, required = future_to_info[future]
            try:
                val, logs = future.result()
                member_results[member_name] = val
                all_logs.extend(logs)
                rctx._step_results[f"{ensemble_name}.{member_name}"] = StepResult(
                    name=f"{ensemble_name}.{member_name}",
                    value=val,
                    status="success",
                    attempts=logs,
                )
            except Exception as exc:
                fail_log = AttemptLog(
                    step=f"{ensemble_name}.{member_name}",
                    attempt=1,
                    status="error",
                    errors=[str(exc)],
                )
                all_logs.append(fail_log)
                if required:
                    required_errors[member_name] = exc
                    logger.warning(
                        "Ensemble '%s': required member '%s' failed: %s",
                        ensemble_name,
                        member_name,
                        exc,
                    )
                else:
                    member_results[member_name] = None
                    rctx._step_results[f"{ensemble_name}.{member_name}"] = StepResult(
                        name=f"{ensemble_name}.{member_name}",
                        value=None,
                        status="failed",
                    )
                    logger.info(
                        "Ensemble '%s': optional member '%s' failed (continuing): %s",
                        ensemble_name,
                        member_name,
                        exc,
                    )

    if required_errors:
        first_name, first_exc = next(iter(required_errors.items()))
        raise RuntimeError(
            f"Ensemble step '{ensemble_name}': required member '{first_name}' failed"
        ) from first_exc

    # Collect succeeded members in spec order (deterministic)
    succeeded: list[dict[str, Any]] = [
        {"name": mn, "model": mk, "output": member_results[mn]}
        for mn, mk, _ms, _req in member_steps
        if member_results.get(mn) is not None
    ]

    if not succeeded:
        return None, all_logs

    # ── Optionally run judge ───────────────────────────────────────────────────
    if judge_spec and len(succeeded) > 1:
        judge_condition: str = judge_spec.get("condition", "all_succeeded")
        required_names = {mn for mn, _mk, _ms, req in member_steps if req}

        should_judge = False
        if judge_condition == "all_succeeded":
            should_judge = all(member_results.get(n) is not None for n in required_names)
        elif judge_condition == "any_succeeded":
            should_judge = True

        if should_judge:
            try:
                judge_val, judge_logs = _run_judge(
                    step=step,
                    judge_spec=judge_spec,
                    succeeded=succeeded,
                    rctx=rctx,
                    execute_member=execute_member,
                    pipeline_dir=pipeline_dir,
                    use_cache=use_cache,
                    refresh_cache=refresh_cache,
                    dry_run=dry_run,
                )
                all_logs.extend(judge_logs)
                if judge_val is not None:
                    return judge_val, all_logs
                logger.warning(
                    "Ensemble '%s': judge returned None, falling back to best member",
                    ensemble_name,
                )
            except Exception as exc:
                logger.warning(
                    "Ensemble '%s': judge failed (%s), falling back to best member",
                    ensemble_name,
                    exc,
                )

    # Return first succeeded member result (spec order = priority order)
    return succeeded[0]["output"], all_logs


def _run_judge(
    step: dict[str, Any],
    judge_spec: dict[str, Any],
    succeeded: list[dict[str, Any]],
    rctx: RunContext,
    execute_member: Callable[..., tuple[Any, list[AttemptLog]]],
    pipeline_dir: Path,
    use_cache: bool,
    refresh_cache: bool,
    dry_run: bool,
) -> tuple[Any, list[AttemptLog]]:
    """Build and execute the judge LLM step."""
    from jinja2 import Environment, StrictUndefined

    ensemble_name: str = step["name"]
    step_schema_cls: Any = step.get("_schema_cls")

    judge_step: dict[str, Any] = {
        "name": f"{ensemble_name}._judge",
        "type": "llm",
        "model": judge_spec.get("model", ""),
    }
    if step_schema_cls is not None:
        judge_step["_schema_cls"] = step_schema_cls

    for k in (
        "temperature",
        "top_p",
        "max_tokens",
        "seed",
        "max_attempts",
        "error_feedback",
        "retry_hint",
        "system",
        "schema_strict",
        "retry_on",
        "max_feedback_tokens",
    ):
        if k in judge_spec:
            judge_step[k] = judge_spec[k]

    if "prompt" in judge_spec:
        # User provided full judge prompt — use it directly
        judge_step["prompt"] = judge_spec["prompt"]
    else:
        # Auto-compose: render the original member prompt then append judge suffix
        step_prompt: str | None = step.get("prompt")
        template_ctx = {
            "ctx": rctx._input,
            "steps": {n: sr.value for n, sr in rctx._step_results.items()},
        }

        rendered_base = ""
        if step_prompt:
            from ..prompt import render_prompt

            prompt_path = pipeline_dir / step_prompt
            rendered_base = render_prompt(
                prompt_path.parent,
                prompt_path.name,
                **template_ctx,
            )

        # Serialize member outputs for template
        members_ctx = [
            {
                "name": m["name"],
                "model": m["model"],
                "output": json.dumps(
                    m["output"].model_dump() if hasattr(m["output"], "model_dump") else m["output"],
                    indent=2,
                ),
            }
            for m in succeeded
        ]

        schema_hint = ""
        if step_schema_cls is not None:
            from ..schema_builder import model_to_schema_hint

            schema_hint = model_to_schema_hint(step_schema_cls)

        env = Environment(
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        suffix = env.from_string(_DEFAULT_JUDGE_SUFFIX).render(
            members=members_ctx,
            schema_hint=schema_hint,
        )
        judge_step["prompt_string"] = rendered_base + suffix

    return execute_member(
        judge_step,
        rctx,
        use_cache=use_cache,
        refresh_cache=refresh_cache,
        dry_run=dry_run,
    )
