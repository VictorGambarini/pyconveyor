"""BenchmarkRunner — evaluate pipelines against golden-standard benchmark cases."""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .runner import PipelineRunner
from .steps.llm_step import AttemptLog

logger = logging.getLogger("pyconveyor.benchmark")

_IGNORE = "$ignore"
_ORDERED = "$ordered"


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class FieldScore:
    """Accuracy score for a single field within a step output."""

    field: str
    actual: Any
    expected: Any
    score: float  # 0.0–1.0
    status: str = "scored"  # "scored" | "ignored"


@dataclass
class StepScore:
    """Accuracy score for a single step within a benchmark case."""

    step_name: str
    score: float  # 0.0–1.0
    status: str  # "scored" | "missing" | "ignored"
    field_scores: list[FieldScore] = field(default_factory=list)


@dataclass
class CaseResult:
    """Result of running one benchmark case through one pipeline."""

    case_name: str
    pipeline_path: str
    status: str  # "ok" | "error"
    step_scores: dict[str, StepScore]
    overall_score: float  # mean score across expected steps
    error: str | None
    elapsed_seconds: float
    attempt_logs: list[AttemptLog] = field(default_factory=list)
    actuals: dict[str, Any] = field(default_factory=dict)
    expecteds: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineBenchmarkResult:
    """Aggregated benchmark results for one pipeline across all cases."""

    pipeline_path: str
    cases: list[CaseResult]
    step_mean_accuracy: dict[str, float]  # step_name -> mean score
    step_pass_rate: dict[str, float]       # step_name -> fraction of cases >= threshold
    overall_mean_accuracy: float
    overall_pass_rate: float


@dataclass
class BenchmarkSummary:
    """Top-level benchmark result containing all pipeline results."""

    pipelines: list[PipelineBenchmarkResult]
    case_names: list[str]
    pass_threshold: float


# ── BenchmarkRunner ────────────────────────────────────────────────────────────

class BenchmarkRunner:
    """Run benchmark cases against one or more pipelines and compare results.

    Benchmark cases live in subdirectories of *benchmark_dir*::

        benchmarks/
          case_001/
                        input.yaml    — pipeline input dict (or input.json)
                        expected.yaml — {step_name: {field: value, ...}, ...} (or expected.json)
          case_002/
            ...

        Only steps present in ``expected.*`` are scored.  Any step not mentioned
    is silently ignored.  A step whose value is a Pydantic model is scored
    field-by-field; nested dicts are recursed into; lists use set-overlap
    for scalars and best-match pairing for dicts.

    The ``$ignore`` sentinel excludes a field, list element, or entire step
    from scoring (excluded from the denominator).  The ``{"$ordered": [...]}``
    directive forces positional list matching instead of the default
    order-independent strategies.

    Custom comparators let you override the default exact-match logic for any
    step or field::

        runner = BenchmarkRunner(
            "benchmarks/",
            pipelines=["pipeline.yaml"],
            comparators={
                "extract.description": lambda a, e: float(a.lower() == e.lower()),
            },
        )

    Comparators are skipped for expected values equal to ``"$ignore"``.

    Args:
        benchmark_dir: Directory containing benchmark case subdirectories.
        pipelines: One or more paths to pipeline YAML files.
        comparators: Optional map of ``"step"`` or ``"step.field"`` keys to
            callables ``(actual, expected) -> float`` returning 0.0–1.0.
        pass_threshold: Minimum overall score for a case to count as passed
            (default: 1.0).
        schemas: Optional schema overrides forwarded to each PipelineRunner.
    """

    def __init__(
        self,
        benchmark_dir: str | Path,
        pipelines: list[str | Path],
        comparators: dict[str, Callable[[Any, Any], float]] | None = None,
        pass_threshold: float = 1.0,
        schemas: dict[str, type] | None = None,
        output_format: str | None = None,
    ) -> None:
        self._benchmark_dir = Path(benchmark_dir)
        self._pipeline_paths = [Path(p) for p in pipelines]
        self._comparators: dict[str, Callable[[Any, Any], float]] = comparators or {}
        self._pass_threshold = pass_threshold
        self._schemas = schemas
        self._output_format = output_format  # None, "json", or "yaml"
        self._cases = self._discover_cases()

    # ── Case discovery ─────────────────────────────────────────────────────────

    def _discover_cases(self) -> list[dict[str, Any]]:
        if not self._benchmark_dir.exists():
            raise FileNotFoundError(
                f"Benchmark directory not found: {self._benchmark_dir}"
            )
        cases: list[dict[str, Any]] = []
        for case_dir in sorted(self._benchmark_dir.iterdir()):
            if not case_dir.is_dir():
                continue
            input_payload, input_fmt = self._load_case_payload(case_dir, "input")
            expected_payload, _ = self._load_case_payload(case_dir, "expected")
            if input_payload is None or expected_payload is None:
                logger.debug(
                    "Skipping %s: missing input.{json,yaml,yml} or expected.{json,yaml,yml}",
                    case_dir.name,
                )
                continue
            if expected_payload == _IGNORE:
                raise ValueError(
                    f"Case '{case_dir.name}': expected cannot be a bare "
                    f"'{_IGNORE}' — every field would be unscored. "
                    f"To ignore a step, set its value to '{_IGNORE}' instead."
                )
            cases.append({
                "name": case_dir.name,
                "input": self._expand_file_refs(input_payload, case_dir),
                "expected": expected_payload,
                "_input_format": input_fmt,
            })
        return cases

    def _load_case_payload(self, case_dir: Path, stem: str) -> tuple[Any | None, str]:
        candidates = [
            case_dir / f"{stem}.json",
            case_dir / f"{stem}.yaml",
            case_dir / f"{stem}.yml",
        ]
        existing = [p for p in candidates if p.exists()]
        if not existing:
            return None, ""
        if len(existing) > 1:
            names = ", ".join(p.name for p in existing)
            raise ValueError(
                f"Case '{case_dir.name}' has multiple {stem} files ({names}); keep only one"
            )

        payload_file = existing[0]
        fmt = "json" if payload_file.suffix == ".json" else "yaml"
        text = payload_file.read_text(encoding="utf-8")
        if payload_file.suffix == ".json":
            return json.loads(text), fmt
        return yaml.safe_load(text), fmt

    def _expand_file_refs(self, value: Any, case_dir: Path) -> Any:
        if isinstance(value, dict):
            if set(value.keys()) == {"$file"}:
                ref = value.get("$file")
                if not isinstance(ref, str) or not ref.strip():
                    raise ValueError(
                        f"Case '{case_dir.name}': $file must be a non-empty string"
                    )
                file_path = Path(ref)
                if not file_path.is_absolute():
                    file_path = case_dir / file_path
                if not file_path.exists():
                    raise FileNotFoundError(
                        f"Case '{case_dir.name}': referenced file not found: {file_path}"
                    )
                return file_path.read_text(encoding="utf-8")
            return {k: self._expand_file_refs(v, case_dir) for k, v in value.items()}
        if isinstance(value, list):
            return [self._expand_file_refs(v, case_dir) for v in value]
        return value

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self) -> BenchmarkSummary:
        """Run all benchmark cases against all pipelines.

        Returns:
            :class:`BenchmarkSummary` with per-pipeline and per-case results.
        """
        results = [self._run_pipeline(p) for p in self._pipeline_paths]
        return BenchmarkSummary(
            pipelines=results,
            case_names=[c["name"] for c in self._cases],
            pass_threshold=self._pass_threshold,
        )

    # ── Internal execution ─────────────────────────────────────────────────────

    def _run_pipeline(self, pipeline_path: Path) -> PipelineBenchmarkResult:
        runner = PipelineRunner(pipeline_path, schemas=self._schemas)
        cases = [self._run_case(runner, pipeline_path, c) for c in self._cases]
        return self._aggregate(pipeline_path, cases)

    def _run_case(
        self,
        runner: PipelineRunner,
        pipeline_path: Path,
        case: dict[str, Any],
    ) -> CaseResult:
        # Resolve output format: CLI flag > input format > json default
        output_format = self._output_format or case.get("_input_format", "json")
        case_input = dict(case["input"])
        case_input["_output_format"] = output_format

        t0 = time.perf_counter()
        try:
            rctx = runner.run(case_input)
        except Exception as exc:
            logger.warning("Case '%s' raised: %s", case["name"], exc)
            return CaseResult(
                case_name=case["name"],
                pipeline_path=str(pipeline_path),
                status="error",
                step_scores={},
                overall_score=0.0,
                error=str(exc),
                elapsed_seconds=time.perf_counter() - t0,
            )

        elapsed = time.perf_counter() - t0

        if rctx.failed:
            fs = rctx.failure_state
            return CaseResult(
                case_name=case["name"],
                pipeline_path=str(pipeline_path),
                status="error",
                step_scores={},
                overall_score=0.0,
                error=str(fs.exception) if fs else "pipeline failed",
                elapsed_seconds=elapsed,
            )

        expected: dict[str, Any] = case["expected"]
        step_scores: dict[str, StepScore] = {}
        actuals: dict[str, Any] = {}
        expecteds: dict[str, Any] = dict(expected)

        for step_name, expected_value in expected.items():
            sr = rctx.steps.get(step_name)
            if sr is None:
                step_scores[step_name] = StepScore(
                    step_name=step_name, score=0.0, status="missing"
                )
                continue
            score, status, fscores = self._score_step(
                step_name, sr.value, expected_value
            )
            step_scores[step_name] = StepScore(
                step_name=step_name,
                score=score,
                status=status,
                field_scores=fscores,
            )
            act = sr.value
            if hasattr(act, "model_dump"):
                act = act.model_dump()
            actuals[step_name] = act

        scored = [s.score for s in step_scores.values() if s.status == "scored"]
        overall = sum(scored) / len(scored) if scored else 0.0
        summary = rctx.summary()

        return CaseResult(
            case_name=case["name"],
            pipeline_path=str(pipeline_path),
            status="ok",
            step_scores=step_scores,
            overall_score=overall,
            error=None,
            elapsed_seconds=elapsed,
            attempt_logs=summary.attempt_logs,
            actuals=actuals,
            expecteds=expecteds,
        )

    # ── Scoring ────────────────────────────────────────────────────────────────

    def _score_step(
        self, step_name: str, actual: Any, expected: Any
    ) -> tuple[float, str, list[FieldScore]]:
        """Score a step's actual output against its expected value.

        Returns ``(score, status, field_scores)`` where *status* is one of
        ``"scored"``, ``"ignored"``, or ``"missing"`` (caller sets ``"missing"``).
        """
        # Step-level $ignore: the entire step is excluded from scoring
        if expected == _IGNORE:
            return 0.0, "ignored", [
                FieldScore("<value>", actual, expected, 0.0, status="ignored")
            ]

        # Step-level custom comparator takes precedence
        if step_name in self._comparators:
            score = float(self._comparators[step_name](actual, expected))
            return score, "scored", [FieldScore("<value>", actual, expected, score)]

        # Convert top-level Pydantic model to dict
        if hasattr(actual, "model_dump"):
            actual = actual.model_dump()

        fscores = self._score_value(actual, expected, step_name)

        scored = [f for f in fscores if f.status == "scored"]
        if not scored:
            return 0.0, "ignored", fscores

        mean = sum(f.score for f in scored) / len(scored)
        return mean, "scored", fscores

    def _score_value(
        self, actual: Any, expected: Any, path: str
    ) -> list[FieldScore]:
        """Recursively score any value — dict, list, scalar — against its
        expected counterpart.  *path* is the dotted field path used in
        :class:`FieldScore` names (e.g. ``"greet.message"``).
        """
        # Convert nested Pydantic models at any depth
        if hasattr(actual, "model_dump"):
            actual = actual.model_dump()

        # Sentinel: exclude this subtree from scoring
        if expected == _IGNORE:
            return [FieldScore(path, actual, expected, 0.0, status="ignored")]

        # Custom comparator registered for this exact path
        if path in self._comparators:
            score = float(self._comparators[path](actual, expected))
            return [FieldScore(path, actual, expected, score)]

        # $ordered directive: positional list matching
        if (
            isinstance(expected, dict)
            and len(expected) == 1
            and _ORDERED in expected
            and isinstance(expected[_ORDERED], list)
        ):
            return self._score_list_positional(actual, expected[_ORDERED], path)

        # Dict: field-by-field recursion
        if isinstance(expected, dict):
            return self._score_dict_fields(actual, expected, path)

        # List: auto-detect set-overlap (scalars) or best-match (dicts)
        if isinstance(expected, list):
            return self._score_list_auto(actual, expected, path)

        # Scalar: exact equality
        score = 1.0 if actual == expected else 0.0
        return [FieldScore(path, actual, expected, score)]

    # ── Dict scoring ────────────────────────────────────────────────────────

    def _score_dict_fields(
        self, actual: Any, expected: dict[str, Any], path: str
    ) -> list[FieldScore]:
        """Score each key of *expected* against the corresponding key in *actual*."""
        actual_dict = actual if isinstance(actual, dict) else {}
        fscores: list[FieldScore] = []
        for fname, exp_val in expected.items():
            field_path = f"{path}.{fname}" if path else fname
            act_val = actual_dict.get(fname)
            fscores.extend(self._score_value(act_val, exp_val, field_path))
        return fscores

    # ── List scoring (auto-detect strategy) ──────────────────────────────────

    def _score_list_auto(
        self, actual: Any, expected: list[Any], path: str
    ) -> list[FieldScore]:
        """Score a list using set-overlap for scalars or best-match for dicts."""
        if not isinstance(actual, list):
            return [FieldScore(path, actual, expected, 0.0)]

        if not expected:
            return [FieldScore(path, actual, expected, 0.0, status="ignored")]

        # Look at non-$ignore elements to decide strategy
        sample = [e for e in expected if e != _IGNORE]
        if not sample or not isinstance(sample[0], dict):
            return self._score_list_scalars(actual, expected, path)
        return self._score_list_of_dicts(actual, expected, path)

    # ── Set-based overlap (default for scalar/element lists) ─────────────────

    def _score_list_scalars(
        self, actual: list[Any], expected: list[Any], path: str
    ) -> list[FieldScore]:
        """Set-based overlap with :data:`_IGNORE` wildcard elements."""
        non_ignored = [e for e in expected if e != _IGNORE]
        ignored_count = len(expected) - len(non_ignored)

        exp_counts = Counter(non_ignored)
        act_counts = Counter(actual)

        matched = 0
        for val, exp_cnt in exp_counts.items():
            matched += min(exp_cnt, act_counts.get(val, 0))

        remaining_actual = len(actual) - matched
        ignored_satisfied = min(ignored_count, remaining_actual)

        total = matched + ignored_satisfied
        score = total / len(expected)
        return [FieldScore(path, actual, expected, score)]

    # ── Positional list matching ($ordered) ──────────────────────────────────

    def _score_list_positional(
        self, actual: Any, expected: list[Any], path: str
    ) -> list[FieldScore]:
        """Position-by-position comparison for ``{"$ordered": [...]}`` lists."""
        if not isinstance(actual, list):
            return [FieldScore(path, actual, expected, 0.0)]

        max_len = max(len(actual), len(expected))
        if max_len == 0:
            return [FieldScore(path, actual, expected, 0.0, status="ignored")]

        total = 0.0
        for i in range(max_len):
            if i >= len(expected):
                total += 0.0
            elif expected[i] == _IGNORE:
                total += 1.0 if i < len(actual) else 0.0
            elif i >= len(actual):
                total += 0.0
            else:
                item_fscores = self._score_value(
                    actual[i], expected[i], f"{path}[{i}]"
                )
                item_scored = [f for f in item_fscores if f.status == "scored"]
                item_score = (
                    sum(f.score for f in item_scored) / len(item_scored)
                    if item_scored
                    else 0.0
                )
                total += item_score

        return [FieldScore(path, actual, expected, total / max_len)]

    # ── Best-match dict list (order-independent) ─────────────────────────────

    def _score_list_of_dicts(
        self, actual: list[Any], expected: list[Any], path: str
    ) -> list[FieldScore]:
        """Greedy best-match pairing for lists of dicts."""
        non_ignored = [e for e in expected if e != _IGNORE]
        ignored_count = len(expected) - len(non_ignored)

        unmatched = list(range(len(actual)))
        total_score = 0.0

        for exp_item in non_ignored:
            if not unmatched:
                total_score += 0.0
                continue

            best_score = -1.0
            best_idx = -1
            for ui in unmatched:
                item_fscores = self._score_value(
                    actual[ui], exp_item, f"{path}[{ui}]"
                )
                item_scored = [f for f in item_fscores if f.status == "scored"]
                item_score = (
                    sum(f.score for f in item_scored) / len(item_scored)
                    if item_scored
                    else 0.0
                )
                if item_score > best_score:
                    best_score = item_score
                    best_idx = ui

            total_score += best_score
            if best_idx >= 0:
                unmatched.remove(best_idx)

        ignored_satisfied = min(ignored_count, len(unmatched))
        total = total_score + ignored_satisfied
        score = total / len(expected) if expected else 0.0
        return [FieldScore(path, actual, expected, score)]

    # ── Aggregation ────────────────────────────────────────────────────────────

    def _aggregate(
        self, pipeline_path: Path, cases: list[CaseResult]
    ) -> PipelineBenchmarkResult:
        step_buckets: dict[str, list[float]] = {}
        for case in cases:
            for sname, ss in case.step_scores.items():
                if ss.status == "ignored":
                    continue
                step_buckets.setdefault(sname, []).append(ss.score)

        step_mean = {k: sum(v) / len(v) for k, v in step_buckets.items()}
        step_pass = {
            k: sum(1 for s in v if s >= self._pass_threshold) / len(v)
            for k, v in step_buckets.items()
        }

        ok_scores = [c.overall_score for c in cases if c.status == "ok"]
        overall_mean = sum(ok_scores) / len(ok_scores) if ok_scores else 0.0
        overall_pass = (
            sum(
                1
                for c in cases
                if c.status == "ok" and c.overall_score >= self._pass_threshold
            )
            / len(cases)
            if cases
            else 0.0
        )

        return PipelineBenchmarkResult(
            pipeline_path=str(pipeline_path),
            cases=cases,
            step_mean_accuracy=step_mean,
            step_pass_rate=step_pass,
            overall_mean_accuracy=overall_mean,
            overall_pass_rate=overall_pass,
        )
