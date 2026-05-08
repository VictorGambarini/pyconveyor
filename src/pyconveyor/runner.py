"""PipelineRunner, RunContext, and related data classes.

This is the heart of pyconveyor.  You describe a workflow in YAML, point
``PipelineRunner`` at it, and call ``runner.run(input_data)``.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from ._utils import expand_env_vars, import_callable, suggest
from .cache import ResponseCache
from .errors import (
    CallableImportError,
    ModelRefError,
    PipelineAbortError,
    PipelineLoadError,
    SchemaRefError,
    StepConfigError,
)
from .expr import (
    _NullSafeProxy,
    _StepsProxy,
    resolve_value,
    validate_all_expressions,
    validate_expression,
)
from .llm import make_client
from .steps.condition_step import execute_condition_step
from .steps.llm_step import AttemptLog, execute_llm_step
from .steps.parallel_step import execute_parallel_step
from .steps.script_step import execute_script_step

logger = logging.getLogger("pyconveyor.runner")

load_dotenv(override=False)  # load .env once at import time (non-invasive)


# ── Result data classes ────────────────────────────────────────────────────────

@dataclass
class StepResult:
    """Wraps a step's output with metadata.  Proxies attribute access to the inner value."""

    name: str
    value: Any  # the actual output (Pydantic model, dict, None, …)
    status: str  # "success" | "failed" | "skipped"
    attempts: list[AttemptLog] = field(default_factory=list)

    @property
    def last_attempt(self) -> AttemptLog | None:
        return self.attempts[-1] if self.attempts else None

    # -- proxy access to the inner value --------------------------------------
    def __getattr__(self, name: str) -> Any:
        # Only reached when 'name' is not a real attribute of StepResult
        val = object.__getattribute__(self, "value")
        if val is None:
            return None
        if isinstance(val, dict):
            if name in val:
                return val[name]
        try:
            return getattr(val, name)
        except AttributeError:
            return None

    def __getitem__(self, key: Any) -> Any:
        val = object.__getattribute__(self, "value")
        if val is None:
            return None
        try:
            return val[key]
        except (KeyError, IndexError, TypeError):
            return None

    def __bool__(self) -> bool:
        return object.__getattribute__(self, "value") is not None

    def __repr__(self) -> str:
        val = object.__getattribute__(self, "value")
        return f"StepResult(name={self.name!r}, status={self.status!r}, value={val!r})"


@dataclass
class FailureState:
    """Information about the step that caused the pipeline to fail."""

    step_name: str
    exception: BaseException


@dataclass
class TokenCount:
    input: int = 0
    output: int = 0
    total: int = 0


@dataclass
class RunSummary:
    """Structured summary of a pipeline run."""

    steps_run: list[str] = field(default_factory=list)
    steps_failed: list[str] = field(default_factory=list)
    steps_skipped: list[str] = field(default_factory=list)
    llm_calls: int = 0
    total_tokens: TokenCount = field(default_factory=TokenCount)
    elapsed_seconds: float = 0.0
    attempt_logs: list[AttemptLog] = field(default_factory=list)
    validation_warnings: list[dict[str, Any]] = field(default_factory=list)
    vocab_suggestions: list[Any] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0


# ── RunContext ─────────────────────────────────────────────────────────────────

class RunContext:
    """Per-run state carrier.

    Access step results via ``rctx.steps["step_name"]`` (returns a ``StepResult``).
    Check for failure via ``rctx.failed`` and ``rctx.failure_state``.
    """

    def __init__(self, input_data: dict[str, Any]) -> None:
        self._input = input_data
        self._step_results: dict[str, StepResult] = {}
        self.metadata: dict[str, Any] = {"attempt_logs": []}
        self.failed: bool = False
        self.failure_state: FailureState | None = None
        self._start_time: float = time.monotonic()
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._validation_warnings: list[dict[str, Any]] = []
        self._vocab_suggestions: list[Any] = []
        self._llm_calls: int = 0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0

    # -- public API ------------------------------------------------------------

    @property
    def steps(self) -> dict[str, StepResult]:
        """Dict of step name → StepResult (with proxy attribute access)."""
        return self._step_results

    def summary(self) -> RunSummary:
        """Return a structured summary of this run."""
        elapsed = time.monotonic() - self._start_time
        steps_run: list[str] = []
        steps_failed: list[str] = []
        steps_skipped: list[str] = []
        for name, sr in self._step_results.items():
            if sr.status == "success":
                steps_run.append(name)
            elif sr.status == "failed":
                steps_failed.append(name)
            elif sr.status == "skipped":
                steps_skipped.append(name)

        return RunSummary(
            steps_run=steps_run,
            steps_failed=steps_failed,
            steps_skipped=steps_skipped,
            llm_calls=self._llm_calls,
            total_tokens=TokenCount(
                input=self._total_input_tokens,
                output=self._total_output_tokens,
                total=self._total_input_tokens + self._total_output_tokens,
            ),
            elapsed_seconds=elapsed,
            attempt_logs=list(self.metadata.get("attempt_logs", [])),
            validation_warnings=list(self._validation_warnings),
            vocab_suggestions=list(self._vocab_suggestions),
            cache_hits=self._cache_hits,
            cache_misses=self._cache_misses,
        )

    # -- expression context build ----------------------------------------------

    def _expr_context(self) -> dict[str, Any]:
        """Build the namespace dict passed to expression evaluation."""
        # steps: _StepsProxy of raw result values
        raw_values = {
            name: sr.value for name, sr in self._step_results.items()
        }
        return {
            "ctx": _NullSafeProxy(self._input),
            "steps": _StepsProxy(raw_values),
        }


# ── PipelineRunner ─────────────────────────────────────────────────────────────

class PipelineRunner:
    """Load a YAML pipeline spec and run it against input data.

    Example::

        runner = PipelineRunner("pipeline.yaml")
        result = runner.run({"document": "...", "doi": "10.1000/x"})
        if not result.failed:
            print(result.steps["extract"].value)
    """

    def __init__(self, pipeline_path: str | Path) -> None:
        self._path = Path(pipeline_path).resolve()
        self._dir = self._path.parent
        self._spec = self._load_and_validate(self._path)
        self._clients: dict[str, Any] = {}  # model_name → client (lazy init)
        self._caches: dict[str, ResponseCache | None] = {}
        self._hooks: dict[str, list[Callable[..., Any]]] = {
            "on_step_end": [],
            "on_llm_call": [],
        }

    # ── Hooks ──────────────────────────────────────────────────────────────────

    def on_step_end(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a callback called after each step completes.

        Signature: ``fn(step_name: str, result: Any, rctx: RunContext) -> None``
        """
        self._hooks["on_step_end"].append(fn)
        return fn

    def on_llm_call(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a callback called after each LLM API call.

        Signature: ``fn(step_name: str, model: str, response: Any) -> None``
        """
        self._hooks["on_llm_call"].append(fn)
        return fn

    # ── Public run API ─────────────────────────────────────────────────────────

    def run(
        self,
        input_data: dict[str, Any],
        model_overrides: dict[str, dict[str, Any]] | None = None,
        use_cache: bool = True,
        refresh_cache: bool = False,
        dry_run: bool = False,
    ) -> RunContext:
        """Execute the pipeline against *input_data*.

        Args:
            input_data: Dict of inputs accessible as ``ctx.*`` in expressions and
                template variables.
            model_overrides: Per-model parameter overrides applied at run time.
                Merged on top of the YAML model config without mutating the
                loaded spec.
            use_cache: Whether to check the response cache (if configured).
            refresh_cache: Ignore cached responses; overwrite on success.
            dry_run: Skip LLM calls and fn calls; validates expressions only.

        Returns:
            ``RunContext`` with ``failed``, ``failure_state``, and ``steps``.
        """
        rctx = RunContext(input_data)
        effective_models = self._effective_models(model_overrides)

        try:
            self._run_steps(
                self._spec.get("steps", []),
                rctx,
                effective_models,
                use_cache=use_cache,
                refresh_cache=refresh_cache,
                dry_run=dry_run,
            )
        except PipelineAbortError as e:
            rctx.failed = True
            rctx.failure_state = FailureState(e.step_name, e.cause)
            logger.error("Pipeline aborted: %s", e)

        return rctx

    # ── Internal step execution ────────────────────────────────────────────────

    def _run_steps(
        self,
        steps: list[dict[str, Any]],
        rctx: RunContext,
        effective_models: dict[str, dict[str, Any]],
        use_cache: bool,
        refresh_cache: bool,
        dry_run: bool,
    ) -> None:
        for step in steps:
            name: str = step["name"]
            on_error: str = step.get("on_error", "raise")

            # Step-level condition gate (separate from 'condition' type)
            condition_expr: str | None = step.get("condition")
            if condition_expr:
                val = resolve_value(f"{{{{ {condition_expr} }}}}", rctx._expr_context(), str(self._path))
                if not val:
                    logger.info("Step '%s': condition false — skipping", name)
                    rctx._step_results[name] = StepResult(
                        name=name, value=None, status="skipped"
                    )
                    continue

            try:
                value, attempt_logs = self._execute_step(
                    step, rctx, effective_models,
                    use_cache=use_cache,
                    refresh_cache=refresh_cache,
                    dry_run=dry_run,
                )
                sr = StepResult(name=name, value=value, status="success", attempts=attempt_logs)
                rctx._step_results[name] = sr
                rctx.metadata["attempt_logs"].extend(attempt_logs)

                # Count LLM calls
                if step.get("type", "llm") == "llm" or (step.get("type") is None and "prompt" in step):
                    rctx._llm_calls += len(attempt_logs)
                    for al in attempt_logs:
                        if al.tokens:
                            rctx._total_input_tokens += al.tokens.get("prompt_tokens", 0)
                            rctx._total_output_tokens += al.tokens.get("completion_tokens", 0)

                for hook in self._hooks["on_step_end"]:
                    try:
                        hook(name, value, rctx)
                    except Exception as he:
                        logger.warning("on_step_end hook error: %s", he)

            except Exception as exc:
                on_failure_ref: str | None = step.get("on_failure")
                if on_failure_ref:
                    try:
                        on_failure_fn = import_callable(on_failure_ref, str(self._path))
                        on_failure_fn(name, exc, rctx)
                    except Exception as fe:
                        logger.warning("on_failure hook '%s' raised: %s", on_failure_ref, fe)

                sr = StepResult(name=name, value=None, status="failed")
                rctx._step_results[name] = sr

                if on_error == "raise":
                    raise PipelineAbortError(name, exc) from exc
                elif on_error == "continue":
                    logger.warning("Step '%s' failed (on_error=continue): %s", name, exc)
                    continue
                elif on_error == "skip_remaining":
                    logger.info(
                        "Step '%s' failed (on_error=skip_remaining): %s", name, exc
                    )
                    # Mark all remaining steps as skipped
                    remaining = steps[steps.index(step) + 1:]
                    for rem in remaining:
                        rctx._step_results[rem["name"]] = StepResult(
                            name=rem["name"], value=None, status="skipped"
                        )
                    break

    def _execute_step(
        self,
        step: dict[str, Any],
        rctx: RunContext,
        effective_models: dict[str, dict[str, Any]],
        use_cache: bool,
        refresh_cache: bool,
        dry_run: bool,
    ) -> tuple[Any, list[AttemptLog]]:
        """Dispatch to the correct step executor.  Returns ``(value, attempt_logs)``."""
        stype: str = step.get("type", "llm")
        name: str = step["name"]
        expr_ctx = rctx._expr_context()

        if stype == "llm":
            model_name: str = step.get("model", "")
            model_config = effective_models.get(model_name, {})
            client = self._get_client(model_name, model_config)
            cache = self._get_cache(model_name, model_config)

            # Resolve vars
            resolved = self._resolve_inputs(step.get("vars", {}), expr_ctx)
            # Also provide full ctx + steps in template vars
            resolved.update({
                "ctx": rctx._input,
                "steps": {n: sr.value for n, sr in rctx._step_results.items()},
            })
            if self._spec.get("vocabularies"):
                from .vocab import Vocabulary
                resolved["vocab"] = {
                    k: v if isinstance(v, Vocabulary) else Vocabulary.from_dict(v)
                    for k, v in self._spec["vocabularies"].items()
                }

            result, logs = execute_llm_step(
                step=step,
                resolved_inputs=resolved,
                client=client,
                model_config=model_config,
                pipeline_dir=self._dir,
                rctx=rctx,
                cache=cache,
                use_cache=use_cache,
                refresh_cache=refresh_cache,
                dry_run=dry_run,
            )
            return result, logs

        elif stype in ("transform", "io", "validate"):
            fn_ref: str = step.get("fn", "")
            fn = self._spec["_callables"].get(fn_ref)
            if fn is None:
                fn = import_callable(fn_ref, str(self._path))
            resolved_inputs = self._resolve_inputs(step.get("inputs", {}), expr_ctx)
            result = execute_script_step(
                step=step,
                resolved_inputs=resolved_inputs,
                fn=fn,
                rctx=rctx,
                dry_run=dry_run,
            )
            return result, []

        elif stype == "parallel":
            def _exec_child(child: dict[str, Any], rctx_shared: RunContext, **kw: Any) -> Any:
                val, logs = self._execute_step(
                    child, rctx_shared, effective_models,
                    use_cache=kw.get("use_cache", True),
                    refresh_cache=kw.get("refresh_cache", False),
                    dry_run=kw.get("dry_run", False),
                )
                # Store child in rctx so expressions can reference them
                rctx_shared._step_results[child["name"]] = StepResult(
                    name=child["name"], value=val, status="success", attempts=logs
                )
                return val

            result_dict = execute_parallel_step(
                step=step,
                rctx=rctx,
                execute_single=_exec_child,
                use_cache=use_cache,
                refresh_cache=refresh_cache,
                dry_run=dry_run,
            )
            return result_dict, []

        elif stype == "condition":
            def _eval_expr(expr: str) -> Any:
                return resolve_value(f"{{{{ {expr} }}}}", rctx._expr_context(), str(self._path))

            def _exec_branch(branch_steps: list[dict[str, Any]], rctx_shared: RunContext) -> Any:
                last_val = None
                for bs in branch_steps:
                    val, logs = self._execute_step(
                        bs, rctx_shared, effective_models,
                        use_cache=use_cache,
                        refresh_cache=refresh_cache,
                        dry_run=dry_run,
                    )
                    rctx_shared._step_results[bs["name"]] = StepResult(
                        name=bs["name"], value=val, status="success", attempts=logs
                    )
                    last_val = val
                return last_val

            result = execute_condition_step(
                step=step,
                rctx=rctx,
                eval_expr=_eval_expr,
                execute_branch=_exec_branch,
            )
            return result, []

        else:
            raise StepConfigError(
                f"Unknown step type '{stype}'",
                file=str(self._path),
                key_path=f"steps[{name}].type",
            )

    # ── Input resolution ───────────────────────────────────────────────────────

    def _resolve_inputs(
        self, inputs: dict[str, Any], expr_ctx: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            k: resolve_value(v, expr_ctx, str(self._path))
            for k, v in inputs.items()
        }

    # ── Model / client helpers ─────────────────────────────────────────────────

    def _effective_models(
        self, overrides: dict[str, dict[str, Any]] | None
    ) -> dict[str, dict[str, Any]]:
        """Merge per-model overrides on top of spec models (non-mutating)."""
        models = {k: dict(v) for k, v in self._spec.get("models", {}).items()}
        if overrides:
            for name, override_params in overrides.items():
                if name in models:
                    models[name] = {**models[name], **override_params}
                else:
                    models[name] = dict(override_params)
        return models

    def _get_client(self, model_name: str, model_config: dict[str, Any]) -> Any:
        if model_name not in self._clients:
            provider = model_config.get("provider", "openai_compat")
            base_url = model_config.get("base_url")
            api_key = model_config.get("api_key")
            mock_responses = model_config.get("mock_responses")
            kwargs: dict[str, Any] = {}
            if mock_responses is not None:
                kwargs["responses"] = mock_responses
            self._clients[model_name] = make_client(
                provider=provider, base_url=base_url, api_key=api_key, **kwargs
            )
        return self._clients[model_name]

    def _get_cache(self, model_name: str, model_config: dict[str, Any]) -> ResponseCache | None:
        if model_name not in self._caches:
            cache_cfg = model_config.get("cache", {})
            if cache_cfg and cache_cfg.get("enabled", False):
                self._caches[model_name] = ResponseCache(
                    directory=cache_cfg.get("dir", ".pyconveyor-cache"),
                    ttl_days=cache_cfg.get("ttl_days"),
                )
            else:
                self._caches[model_name] = None
        return self._caches[model_name]

    # ── YAML loading and validation ────────────────────────────────────────────

    def _load_and_validate(self, path: Path) -> dict[str, Any]:
        """Load, expand env-vars, and validate the pipeline YAML.

        Runs all load-time checks before any run begins:
        - No duplicate step names
        - All model references exist
        - All fn/schema/parser references are importable
        - All expressions pass AST whitelist
        - All step names referenced in expressions are defined
        """
        file_str = str(path)
        try:
            with path.open(encoding="utf-8") as fh:
                raw: dict[str, Any] = yaml.safe_load(fh) or {}
        except yaml.YAMLError as e:
            raise PipelineLoadError(f"YAML parse error: {e}", file=file_str) from e
        except FileNotFoundError as e:
            raise PipelineLoadError(f"Pipeline file not found: {path}", file=file_str) from e

        spec = expand_env_vars(raw)

        # Collect model names
        model_names = set(spec.get("models", {}).keys())
        # Collect parser names
        parser_names = set(spec.get("parsers", {}).keys())

        # Pre-import parsers
        parsers: dict[str, Any] = {}
        for pname, pref in spec.get("parsers", {}).items():
            try:
                parsers[pname] = import_callable(pref, file_str, f"parsers.{pname}")
            except Exception as e:
                raise CallableImportError(str(e), file=file_str, key_path=f"parsers.{pname}") from e

        # Pre-import and resolve all step callables / schemas
        callables: dict[str, Any] = {}
        steps: list[dict[str, Any]] = spec.get("steps", [])
        all_step_names: set[str] = self._collect_step_names(steps)

        self._validate_steps(
            steps, file_str, model_names, parser_names, parsers,
            callables, all_step_names, parent_path=""
        )

        spec["_callables"] = callables
        spec["_parsers"] = parsers

        logger.info("Loaded pipeline '%s' with %d steps", path.name, len(steps))
        return spec

    def _collect_step_names(self, steps: list[dict[str, Any]]) -> set[str]:
        names: set[str] = set()
        for step in steps:
            n = step.get("name")
            if n:
                names.add(n)
            if step.get("type") == "parallel":
                names |= self._collect_step_names(step.get("steps", []))
            if step.get("type") == "condition":
                for branch_key in ("then", "else"):
                    b = step.get(branch_key)
                    if isinstance(b, list):
                        names |= self._collect_step_names(b)
                    elif isinstance(b, dict):
                        names |= self._collect_step_names([b])
        return names

    def _validate_steps(
        self,
        steps: list[dict[str, Any]],
        file_str: str,
        model_names: set[str],
        parser_names: set[str],
        parsers: dict[str, Any],
        callables: dict[str, Any],
        all_step_names: set[str],
        parent_path: str,
    ) -> None:
        seen_names: set[str] = set()

        for i, step in enumerate(steps):
            name = step.get("name")
            if not name:
                raise StepConfigError(
                    f"Step at index {i} is missing required field 'name'",
                    file=file_str,
                    key_path=f"{parent_path}steps[{i}]",
                )
            key_base = f"{parent_path}steps[{i}]({name})"

            if name in seen_names:
                raise StepConfigError(
                    f"Duplicate step name '{name}'",
                    file=file_str,
                    key_path=key_base,
                )
            seen_names.add(name)

            stype = step.get("type", "llm")

            if stype == "llm":
                self._validate_llm_step(
                    step, file_str, model_names, parser_names, parsers,
                    key_base, all_step_names
                )

            elif stype in ("transform", "io", "validate"):
                fn_ref = step.get("fn")
                if not fn_ref:
                    raise StepConfigError(
                        f"Step '{name}' (type={stype}) is missing required field 'fn'",
                        file=file_str,
                        key_path=key_base,
                    )
                try:
                    callables[fn_ref] = import_callable(fn_ref, file_str, f"{key_base}.fn")
                except CallableImportError:
                    raise
                except Exception as e:
                    raise CallableImportError(str(e), file=file_str, key_path=f"{key_base}.fn") from e
                # Validate inputs expressions
                validate_all_expressions(step.get("inputs", {}), file_str, f"{key_base}.inputs")

            elif stype == "parallel":
                children = step.get("steps", [])
                self._validate_steps(
                    children, file_str, model_names, parser_names, parsers,
                    callables, all_step_names, f"{key_base}."
                )

            elif stype == "condition":
                expr = step.get("if")
                if expr:
                    validate_expression(expr, file_str, f"{key_base}.if")
                for branch_key in ("then", "else"):
                    branch = step.get(branch_key)
                    if branch is None:
                        continue
                    branch_steps = branch if isinstance(branch, list) else [branch]
                    if branch_steps and isinstance(branch_steps[0], dict):
                        self._validate_steps(
                            branch_steps, file_str, model_names, parser_names, parsers,
                            callables, all_step_names, f"{key_base}.{branch_key}."
                        )

            # Validate on_failure reference if present
            on_failure = step.get("on_failure")
            if on_failure:
                try:
                    callables[on_failure] = import_callable(
                        on_failure, file_str, f"{key_base}.on_failure"
                    )
                except CallableImportError:
                    raise

            # Validate step-level condition expression
            condition = step.get("condition")
            if condition:
                validate_expression(condition, file_str, f"{key_base}.condition")

    def _validate_llm_step(
        self,
        step: dict[str, Any],
        file_str: str,
        model_names: set[str],
        parser_names: set[str],
        parsers: dict[str, Any],
        key_base: str,
        all_step_names: set[str],
    ) -> None:
        name = step["name"]

        # model: reference
        model_ref = step.get("model")
        if model_ref and model_ref not in model_names:
            s = suggest(model_ref, list(model_names))
            raise ModelRefError(
                f"Model '{model_ref}' is not defined in the models: block. "
                f"Defined models: {sorted(model_names)}",
                file=file_str,
                key_path=f"{key_base}.model",
                suggestion=s,
            )

        # schema: reference
        schema_ref = step.get("schema")
        if schema_ref:
            try:
                schema_cls = _import_schema(schema_ref, file_str, f"{key_base}.schema")
                step["_schema_cls"] = schema_cls
            except SchemaRefError:
                raise

        # parser: reference
        parser_ref = step.get("parser")
        if parser_ref:
            if parser_ref in parser_names:
                step["_parser_fn"] = parsers[parser_ref]
            else:
                # Try as a dotted callable
                try:
                    step["_parser_fn"] = import_callable(
                        parser_ref, file_str, f"{key_base}.parser"
                    )
                except CallableImportError:
                    s = suggest(parser_ref, list(parser_names))
                    raise CallableImportError(
                        f"Parser '{parser_ref}' is not defined in the parsers: block "
                        f"and is not importable as a callable. "
                        f"Defined parsers: {sorted(parser_names)}",
                        file=file_str,
                        key_path=f"{key_base}.parser",
                        suggestion=s,
                    )

        # vars: expressions
        validate_all_expressions(step.get("vars", {}), file_str, f"{key_base}.vars")

        # Log effective retry policy (§10.4)
        has_schema = "_schema_cls" in step
        effective_max = step.get("max_attempts", 3 if has_schema else 1)
        effective_fb = step.get("error_feedback", has_schema)
        logger.info(
            "Step '%s': max_attempts=%d error_feedback=%s",
            name, effective_max, effective_fb
        )


def _import_schema(ref: str, file_str: str, key_path: str) -> type:
    """Import and validate a Pydantic BaseModel reference."""
    from pydantic import BaseModel

    try:
        cls = import_callable(ref, file_str, key_path)
    except CallableImportError:
        raise

    if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
        raise SchemaRefError(
            f"'{ref}' must be a Pydantic BaseModel subclass, got {cls!r}",
            file=file_str,
            key_path=key_path,
        )
    return cls
