# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note:** The YAML pipeline format is treated as a public API subject to the same
> semver rules as the Python API. See the [Versioning Policy](README.md#versioning-policy).

---

## [Unreleased]

### Added

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

[0.1.0]: https://github.com/VictorGambarini/pyconveyor/releases/tag/v0.1.0
