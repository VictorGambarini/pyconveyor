# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest --cov=pyconveyor

# Run a single test file
pytest tests/test_runner.py

# Run a single test by name
pytest tests/test_runner.py::test_function_name -k "keyword"

# Lint
ruff check src tests

# Type check
mypy src
```

## Architecture

**pyconveyor** is a YAML-driven pipeline engine for structured LLM extraction. Pipelines are declared in YAML; the engine handles prompt rendering, schema validation, self-correcting retries, parallel execution, and batching.

### Key design constraint: YAML is the public API. Breaking changes to the YAML schema require a major version bump.

### Execution flow

```
YAML pipeline → PipelineRunner → RunContext
  → for each step: resolve exprs → check condition → execute → store StepResult
  → LLM steps: validate output → retry with error feedback on failure
  → return RunContext
```

### Core modules

- **`runner.py`** — `PipelineRunner`: loads YAML, executes steps in order, returns `RunContext`. This is the heart of the system. `StepResult` and `AttemptLog` live here too.
- **`steps/`** — Step type implementations: `llm`, `transform`, `validate`, `io`, `parallel`, `condition`.
- **`llm.py`** — Provider registry (`@register_provider`), `make_client()` factory, `call_llm()`, `extract_json()`. Built-in providers: `openai_compat` (default), `anthropic`, `mock`.
- **`schema_builder.py`** — Parses inline YAML schemas (`field: type`) or Pydantic model references (`schemas:MyModel`) into Pydantic models via `yaml_dict_to_model()`.
- **`prompt.py`** — Jinja2-based rendering. `render_prompt()` from file, `render_prompt_string()` from string. Strict undefined checking.
- **`expr.py`** — Safe AST-whitelist expression evaluator for YAML condition/value fields. Context variables are `ctx` (pipeline input) and `steps` (prior results). Allowed calls: `first_non_none()`, `active_models()`, `len()`.
- **`batch.py`** — `BatchRunner` with `ThreadPoolExecutor`; returns `BatchResult` with `.successes`, `.failures`, `.error_rate`.
- **`benchmark.py`** — `BenchmarkRunner` compares pipeline outputs to golden cases in `benchmark_dir/case_name/{input.json, expected.json}`.
- **`report.py`** — HTML report generation with Chart.js and Mermaid diagrams.
- **`vocab.py`** — Vocabulary-constrained fields with fuzzy matching and growth policies (`auto`, `human`, `llm`, callable).
- **`cache.py`** — SHA-256 hashed file-based response cache for development. Key = hash of (provider, model, messages, sampling params).
- **`cli.py`** — Commands: `init`, `run`, `validate`, `batch`, `schema`, `visualise`, `benchmark`, `vocab review`.
- **`errors.py`** — Typed exceptions with YAML location context and "did you mean?" suggestions.
- **`graph.py`** — Mermaid DAG generation from YAML pipeline definitions.

### Result types

- `RunContext` — Holds pipeline input, all `StepResult`s, metadata, failure state.
- `StepResult` — Value, status, attempt logs; proxies attribute access to the underlying value.
- `AttemptLog` — Per-LLM-attempt record: step name, attempt number, status, errors, tokens, raw output.
- `RunSummary` — Aggregated counts: steps run/failed/skipped, token totals, timing.

### Error handling in pipelines

Three strategies set via `on_error` in YAML: `raise` (default, aborts), `continue` (logs, moves on), `skip_remaining` (logs, skips rest). Optional `on_failure` callback: `fn(step_name, exc, rctx)`.

### LLM retry loop

On parse or validation failure, the runner re-renders the prompt using an error template that includes truncated previous output and the specific errors, then retries up to `max_attempts` times.

### Tests

Tests live in `tests/`. Fixtures in `tests/fixtures/`: YAML pipelines (`pipelines/`), benchmark golden cases (`benchmarks/`), and domain models/step functions (`schemas.py`, `steps.py`). The `mock` LLM provider is used extensively in tests to avoid real API calls.

### CI

`.github/workflows/ci.yml` runs pytest, mypy, and ruff against Python 3.10–3.14.
