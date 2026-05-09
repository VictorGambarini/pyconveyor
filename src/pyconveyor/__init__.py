"""pyconveyor — Deterministic YAML pipeline engine for structured LLM extraction.

Public API::

    from pyconveyor import PipelineRunner, BatchRunner, generate_mermaid
    from pyconveyor import register_provider
    from pyconveyor.llm import make_client, call_llm, probe_json_mode, extract_json
    from pyconveyor.prompt import render_prompt, render_prompt_string
    from pyconveyor.vocab import VocabField, Vocabulary
"""
from __future__ import annotations

from .batch import BatchResult, BatchRunner, BatchSummary
from .graph import generate_mermaid
from .llm import register_provider
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
]

__version__ = "1.0.1"
