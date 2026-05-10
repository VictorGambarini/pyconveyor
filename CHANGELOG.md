# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note:** The YAML pipeline format is treated as a public API subject to the same
> semver rules as the Python API. See the [Versioning Policy](README.md#versioning-policy).

---

## [Unreleased]

### Added
- Inline YAML schemas: `schema:` on `llm` steps now accepts a field-map dict
  in addition to a `module:Class` string reference.
- `PipelineRunner(schemas={"step": MyModel})` — inject Pydantic models directly
  from Python without a `schemas.py` file.
- `pyconveyor schema infer` — generate a `schemas.py` stub from sample JSON output.
- `{{ schema_hint }}` — auto-generated field description available in all prompt
  templates when a schema is present.
- `pyconveyor init --interactive` — guided project setup; defines fields
  interactively and uses inline YAML schema, no `schemas.py` required.

---

## [1.0.1] — 2026-05-10

### Changed

- README rewritten with full feature overview, examples, CLI reference, and documentation links

---

## [1.0.0] — 2026-05-10

### Added

- `Vocabulary.description` — human-written rationale field; shown to the LLM in the prompt suffix to guide novel-term and `_ideal` decisions
- `Vocabulary.growth_policy` — three built-in modes: `"auto"` (add immediately), `"human"` (queue for CLI review), `"llm"` (LLM decides); also accepts a custom callable `fn(VocabSuggestion) -> bool`
- `Vocabulary.growth_policy_model` — optional model name override for `growth_policy="llm"`; falls back to the pipeline's default model
- `Vocabulary.capture_ideal` — when `True`, the LLM prompt asks for `{field}_ideal` alongside the constrained value; extracted before Pydantic validation and stored in `VocabSuggestion.ideal_value`
- `Vocabulary.inject_prompt` — auto-appends vocab constraints + description + denied terms to the LLM prompt; disable per-step with `inject_vocab_prompt: false`
- `Vocabulary.persist` — `True` or explicit path; vocabulary file is saved after each run that produces suggestions
- `Vocabulary.denied` — set of explicitly rejected terms; not re-surfaced as suggestions; shown to LLM in prompt suffix
- `Vocabulary.pending` — pending suggestions queue used by `"human"` growth policy
- `Vocabulary.add_term()` — add a term to `known` and update the internal lookup
- `Vocabulary.add_pending()` — queue a `VocabSuggestion`, incrementing `seen` if already present
- `Vocabulary.build_prompt_suffix()` — render the vocab constraint block for prompt injection
- `Vocabulary.save(path)` — persist vocabulary YAML (known, pending, denied, metadata)
- `Vocabulary.from_file(path)` — load vocabulary from a YAML file
- `VocabField(vocab="label")` — string reference resolved from the pipeline's `vocabularies:` block; keeps `schemas.py` free of file paths
- `VocabSuggestion.ideal_value` — LLM's unconstrained preferred answer (populated when `capture_ideal=True`)
- `VocabSuggestion.vocab_label` — which vocabulary the suggestion came from
- `{{ vocab_hints }}` Jinja2 variable — pre-rendered vocab constraint block for manual placement in prompt templates
- `pyconveyor vocab review pipeline.yaml` CLI command — interactive review of pending vocab suggestions; shows full list with `seen` counts, accepts by index, writes denied to `denied:` block; `--auto-accept` flag for non-interactive use
- `vocabularies/` directory scaffolded by `pyconveyor init`
- Caching guide (`docs/guides/caching.md`) covering `ResponseCache`, CLI flags, Python API, cache key semantics, and TTL configuration
- `on_llm_call` hook now fires for LLM calls inside `type: parallel` steps (previously only top-level steps)

### Changed

- `Development Status` classifier updated from `3 - Alpha` to `5 - Production/Stable`
- `pyproject.toml` version bumped to `1.0.0` — stable public API

---

## [0.2.0] — 2026-05-09

### Added

- `pyconveyor batch` CLI subcommand — process a JSONL file through a pipeline with configurable parallelism; outputs JSONL results
- `BatchResult` — rich result wrapper returned by `BatchRunner.run_all()`, with `.successes`, `.failures`, `.error_rate`, and `.summary()` properties; fully backward-compatible via `__iter__` and `__getitem__`
- `BatchSummary` dataclass — aggregate statistics (`total`, `succeeded`, `failed`, `error_rate`, `failed_ids`)
- `BatchRunner.on_batch_item_end` hook — callback fired after each item completes, useful for streaming results to a database without waiting for the full batch
- `PipelineRunner.on_run_start` hook — callback fired before any steps execute; `fn(input_data: dict) -> None`
- `PipelineRunner.on_run_end` hook — callback fired after the run completes (success or failure); `fn(rctx: RunContext) -> None`
- `VocabField` pipeline integration — the LLM step now automatically applies vocabulary normalisation (from `json_schema_extra["_pyconveyor_vocab"]`) to Pydantic model fields before validation; novel and fuzzy-matched terms are recorded in `rctx._vocab_suggestions` and surfaced in `RunSummary.vocab_suggestions`
- GitHub Actions CI workflow (`.github/workflows/ci.yml`) — ruff, mypy, pytest on Python 3.10–3.14 matrix
- GitHub Actions publish workflow (`.github/workflows/publish.yml`) — tag-triggered PyPI publish via OIDC Trusted Publisher + GitHub Release creation
- MkDocs + Material theme docs site (`docs/`) — 11 pages covering quickstart, all step types, expressions, providers, CLI reference, and examples
- `.readthedocs.yaml` v2 config targeting Read the Docs at `https://pyconveyor.readthedocs.io`
- Python 3.13 and 3.14 trove classifiers in `pyproject.toml`

---

## [0.1.0] — 2026-05-09

### Added

- `PipelineRunner` — YAML-driven step executor with full load-time validation
- `RunContext` — per-run state carrier with `steps`, `metadata`, `failed`, `failure_state`
- `_NullSafeProxy` — null-safe attribute access for `ctx` in expressions
- Step types: `llm`, `transform`, `validate`, `io`, `parallel`, `condition`
- AST-whitelisted expression evaluator with `ExpressionSecurityError` at pipeline load time
- Rich load-time validation errors with "did you mean?" suggestions (string-distance scoring)
- LLM utilities (`make_client`, `call_llm`, `probe_json_mode`, `extract_json`) importable standalone
- Jinja2 prompt rendering (`render_prompt`, `render_prompt_string`)
- Unified parse + schema error feedback retry loop (§10) with conversation message structure
- `retry_on`, `schema_strict`, `max_feedback_tokens`, `error_template` per-step configuration
- Smart conditional defaults: `max_attempts` and `error_feedback` based on presence of `schema:`
- `last_attempt` accessor on `StepResult` for failure introspection
- Step-level `on_error` (`raise` | `continue` | `skip_remaining`) and `on_failure` hook
- Full model config: `temperature`, `top_p`, `max_tokens`, `seed`, `extra_params`, `pricing`
- Programmatic model overrides via `runner.run(..., model_overrides={})`
- `mock` provider for unit tests without API calls
- `openai_compat` provider (works with OpenAI, Ollama, vLLM, LM Studio)
- Native Anthropic provider (optional dependency)
- Custom provider registration via `@register_provider("name")` decorator
- `BatchRunner` — batch processing with configurable concurrency and optional tqdm progress
- Mermaid DAG visualisation (`generate_mermaid`)
- Dry-run mode (`runner.run(..., dry_run=True)`)
- `RunContext.summary()` with step counts, LLM call counts, elapsed time, attempt logs
- `VocabField` and `Vocabulary` — vocabulary-constrained fields with fuzzy matching
- Response caching for development (file-per-key, TTL support, cache control flags)
- `pyconveyor init` — bootstrap a working pipeline directory
- `pyconveyor run` — run a pipeline from the CLI
- `pyconveyor validate` — validate pipeline YAML with line-number errors
- `pyconveyor schema` — emit JSONSchema for editor autocomplete
- `pyconveyor visualise` — produce Mermaid DAG diagram
- Standard `logging` integration under `pyconveyor.*` namespaces
- `SCHEMA.md` — YAML format reference as a public contract
- Full unit test suite with fixture pipelines — 167 tests, 80% line coverage

### Fixed

- **ISSUE-001**: Fixed 52 ruff lint errors (unused imports, undefined names, bare excepts, unused variables, type annotation issues).
- **ISSUE-002**: Fixed 12 mypy strict-mode type errors (missing `-> None` returns, untyped dicts, improper Optional handling).
- **ISSUE-003**: `pyconveyor validate` / `pyconveyor run` now insert the pipeline directory into `sys.path` so local schema modules are importable without installation.
- **ISSUE-004**: `pyconveyor run --input` now accepts an inline JSON string starting with `{` or `[`, eliminating the spurious `FileNotFoundError` on inline JSON input.

[1.0.1]: https://github.com/VictorGambarini/pyconveyor/releases/tag/v1.0.1
[0.1.0]: https://github.com/VictorGambarini/pyconveyor/releases/tag/v0.1.0
