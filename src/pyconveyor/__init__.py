"""pyconveyor — Deterministic YAML pipeline engine for structured LLM extraction.

Public API::

    from pyconveyor import PipelineRunner, BatchRunner, generate_mermaid
    from pyconveyor import BenchmarkRunner, generate_report
    from pyconveyor import register_provider
    from pyconveyor.llm import make_client, call_llm, probe_json_mode, extract_json
    from pyconveyor.prompt import render_prompt, render_prompt_string
    from pyconveyor.vocab import VocabField, Vocabulary
"""
from __future__ import annotations

from .batch import BatchResult, BatchRunner, BatchSummary
from .benchmark import (
    BenchmarkRunner,
    BenchmarkSummary,
    CaseResult,
    FieldScore,
    PipelineBenchmarkResult,
    StepScore,
)
from .graph import generate_mermaid
from .llm import register_provider
from .report import generate_report
from .runner import (
    FailureState,
    PipelineRunner,
    RunContext,
    RunSummary,
    StepResult,
    TokenCount,
)

__all__ = [
    "PipelineRunner",
    "BatchRunner",
    "BatchResult",
    "BatchSummary",
    "RunContext",
    "RunSummary",
    "StepResult",
    "FailureState",
    "TokenCount",
    "generate_mermaid",
    "register_provider",
    "BenchmarkRunner",
    "BenchmarkSummary",
    "PipelineBenchmarkResult",
    "CaseResult",
    "StepScore",
    "FieldScore",
    "generate_report",
]

__version__ = "1.2.0"
