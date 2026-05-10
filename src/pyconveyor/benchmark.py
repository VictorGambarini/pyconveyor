"""BenchmarkRunner — evaluate pipelines against golden-standard benchmark cases."""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .runner import PipelineRunner
from .steps.llm_step import AttemptLog

logger = logging.getLogger("pyconveyor.benchmark")


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class FieldScore:
    """Accuracy score for a single field within a step output."""

    field: str
    actual: Any
    expected: Any
    score: float  # 0.0–1.0


@dataclass
class StepScore:
    """Accuracy score for a single step within a benchmark case."""

    step_name: str
    score: float  # 0.0–1.0
    status: str  # "scored" | "missing"
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
            input.json    — pipeline input dict
            expected.json — {step_name: {field: value, ...}, ...}
          case_002/
            ...

    Only steps present in ``expected.json`` are scored.  Any step not mentioned
    is silently ignored.  A step whose value is a Pydantic model is scored
    field-by-field; plain scalars and lists are compared with exact equality.

    Custom comparators let you override the default exact-match logic for any
    step or field::

        runner = BenchmarkRunner(
            "benchmarks/",
            pipelines=["pipeline.yaml"],
            comparators={
                "extract.description": lambda a, e: float(a.lower() == e.lower()),
            },
        )

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
    ) -> None:
        self._benchmark_dir = Path(benchmark_dir)
        self._pipeline_paths = [Path(p) for p in pipelines]
        self._comparators: dict[str, Callable[[Any, Any], float]] = comparators or {}
        self._pass_threshold = pass_threshold
        self._schemas = schemas
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
            input_file = case_dir / "input.json"
            expected_file = case_dir / "expected.json"
            if not input_file.exists() or not expected_file.exists():
                logger.debug(
                    "Skipping %s: missing input.json or expected.json", case_dir.name
                )
                continue
            cases.append({
                "name": case_dir.name,
                "input": json.loads(input_file.read_text(encoding="utf-8")),
                "expected": json.loads(expected_file.read_text(encoding="utf-8")),
            })
        return cases

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
        t0 = time.perf_counter()
        try:
            rctx = runner.run(case["input"])
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

        for step_name, expected_value in expected.items():
            sr = rctx.steps.get(step_name)
            if sr is None:
                step_scores[step_name] = StepScore(
                    step_name=step_name, score=0.0, status="missing"
                )
                continue
            score, fscores = self._score_step(step_name, sr.value, expected_value)
            step_scores[step_name] = StepScore(
                step_name=step_name,
                score=score,
                status="scored",
                field_scores=fscores,
            )

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
        )

    # ── Scoring ────────────────────────────────────────────────────────────────

    def _score_step(
        self, step_name: str, actual: Any, expected: Any
    ) -> tuple[float, list[FieldScore]]:
        # Step-level custom comparator takes precedence
        if step_name in self._comparators:
            score = float(self._comparators[step_name](actual, expected))
            return score, [FieldScore("<value>", actual, expected, score)]

        # Dict / Pydantic model: score field-by-field
        if isinstance(expected, dict):
            actual_dict: dict[str, Any] = {}
            if hasattr(actual, "model_dump"):
                actual_dict = actual.model_dump()
            elif isinstance(actual, dict):
                actual_dict = actual

            fscores: list[FieldScore] = []
            for fname, exp_val in expected.items():
                key = f"{step_name}.{fname}"
                act_val = actual_dict.get(fname)
                if key in self._comparators:
                    score = float(self._comparators[key](act_val, exp_val))
                else:
                    score = 1.0 if act_val == exp_val else 0.0
                fscores.append(FieldScore(fname, act_val, exp_val, score))

            mean = sum(f.score for f in fscores) / len(fscores) if fscores else 0.0
            return mean, fscores

        # Scalar / list: exact match
        score = 1.0 if actual == expected else 0.0
        return score, [FieldScore("<value>", actual, expected, score)]

    # ── Aggregation ────────────────────────────────────────────────────────────

    def _aggregate(
        self, pipeline_path: Path, cases: list[CaseResult]
    ) -> PipelineBenchmarkResult:
        step_buckets: dict[str, list[float]] = {}
        for case in cases:
            for sname, ss in case.step_scores.items():
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
