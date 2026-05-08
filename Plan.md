# pyconveyor — Package Plan

> A lightweight, deterministic YAML pipeline engine for structured LLM extraction.
>
> Born from the extraction engine of PlasticDB-AI. Stripped of everything
> domain-specific and published as a reusable library for anyone running
> reproducible, schema-validated LLM extraction workflows.

---

## 1. What it is and why it matters

`pyconveyor` is a **deterministic extraction pipeline runner**. You describe
your workflow in YAML, write prompts in Jinja2, define step logic in plain
Python functions, and point it at any OpenAI-compatible endpoint. The runner
handles model calls, retries, parallel execution, Pydantic schema validation,
conditional branching, and structured result summaries.

The PlasticDB extraction stage proved this pattern in production. pyconveyor
ships that engine as a first-class library.

### What problem it actually solves

The real competition is not LangChain or LlamaIndex. It is:

- **ad-hoc Python scripts** that break when the model output format shifts
- **Jupyter notebooks** that are not reproducible and cannot be scheduled
- **bash glue pipelines** that have no schema guarantees
- **fragile prompt loops** written from scratch for every new extraction task

If pyconveyor can make **reproducible extraction, reliable retries,
schema-safe outputs, and observable runs** simpler than handwritten glue
code, it has earned its place.

### Primary audience

- Researchers running LLM extraction over scientific literature.
- ML/data engineers replacing fragile extraction scripts with a versioned,
  testable pipeline definition.
- Teams who need multi-model reconciliation (primary + reviewer + merge)
  without building the orchestration themselves.

### Words we will never use in marketing

`agent`, `autonomous`, `AI workflow platform`, `tool calling`, `memory`,
`RAG`. These signal the wrong audience and invite feature-creep comparisons
with ecosystems we are not competing with.

### Words that describe what we actually are

`deterministic`, `reproducible`, `schema-driven`, `extraction pipelines`,
`structured outputs`, `multi-model reconciliation`, `research workflows`.

---

## 2. Differentiation

There are overlapping projects — LangGraph, Haystack, PocketFlow,
Prefect/Dagster applied to LLMs — but none match this combination:

| Differentiator | What it means in practice |
|---|---|
| **YAML as a versioned public API** | Breaking schema changes require a major semver bump. Most frameworks treat config as implementation detail. |
| **OpenAI-compat-first** | Works with Ollama, vLLM, LM Studio, Claude proxies, and any hosted endpoint with zero code changes. |
| **Extraction-focused, not agent-focused** | Optimised for classification, annotation, structured record extraction, and multi-pass reconciliation — not chat or tool use. |
| **Explicit DAG, no magic** | Every step, every data dependency, every control flow branch is visible in one YAML file. No hidden state. |
| **Primary/reviewer/reconcile pattern** | Parallel dual-model extraction with a merge/arbitration step is a first-class pattern, not something users have to build. |
| **Self-correcting retries** | When a model returns malformed JSON or schema-invalid output, pyconveyor feeds the error back to the same model so it can fix itself — without code. |
| **Comprehensible in one sitting** | The entire runner is one file. The YAML format has a one-page reference. This is intentional. |

---

## 3. What lives in pyconveyor vs. stays in your project

### Belongs in pyconveyor
| Component | Origin in PlasticDB |
|---|---|
| `PipelineRunner` — YAML step executor | `src/pipeline_runner.py` |
| `RunContext` + `_NullSafeProxy` — per-run state carrier | same |
| Step types: `llm`, `transform`, `validate`, `io`, `parallel`, `condition` | same |
| Constrained expression evaluation between steps | same (redesigned — see §6) |
| Jinja2 prompt rendering (`render_prompt`) | `src/llm_utils.py` |
| OpenAI-compat client factory (`make_client`) | same |
| JSON mode probe (`probe_json_mode`) | same |
| Resilient JSON extraction (`extract_json`) | same |
| LLM call with timeout + json_mode (`call_llm`) | same |
| Retry logic with configurable attempts and delay | embedded in runner |
| Per-step Pydantic schema validation | embedded in runner |
| Validation-error retry feedback loop | new (see §10) |
| Mermaid DAG visualisation (`generate_mermaid`) | `src/pipeline_runner.py` |
| `BatchRunner` — process a list of items through a pipeline | generalised from `StageRunner` |
| CLI: `init`, `run`, `visualise`, `validate`, `schema` | new |

### Stays in your project
| Component | Reason |
|---|---|
| Domain Pydantic schemas (`EntryRecord`, `ExtractionResult`) | domain-specific |
| SQLite / database state machine | application-level concern |
| Step implementations (`pipeline/steps/*.py`) | domain-specific |
| Parser functions (`pipeline/parsers/*.py`) | domain-specific |
| Prompt templates (`*.j2`) | domain-specific |
| Bio utilities, git manager, harvester | domain-specific |

The contract is clean: **pyconveyor owns the runner; you own the steps.**

---

## 4. Package structure

```
pyconveyor/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── LICENSE                       (MIT)
├── SCHEMA.md                     (YAML format reference — a public contract)
│
└── src/
    └── pyconveyor/
        ├── __init__.py           # public API re-exports
        │
        ├── runner.py             # PipelineRunner, RunContext, _NullSafeProxy
        ├── batch.py              # BatchRunner
        ├── llm.py                # make_client, call_llm, probe_json_mode, extract_json
        ├── prompt.py             # render_prompt (Jinja2)
        ├── schema.py             # _validate_output_schema helper
        ├── graph.py              # generate_mermaid
        ├── expr.py               # constrained expression evaluator (see §6)
        ├── vocab.py              # VocabField, Vocabulary, VocabSuggestion
        ├── cache.py              # response cache for development (see §12.5)
        ├── logging.py            # logging configuration helpers (see §7.4)
        ├── errors.py             # typed exceptions with YAML context
        │
        ├── steps/                # built-in step type implementations
        │   ├── llm_step.py
        │   ├── script_step.py
        │   ├── parallel_step.py
        │   └── condition_step.py
        │
        ├── cli.py                # `pyconveyor` CLI entry point
        ├── templates/            # files copied by `pyconveyor init`
        │   ├── pipeline.yaml.tmpl
        │   ├── steps.py.tmpl
        │   └── vscode-settings.json.tmpl
        │
        └── py.typed              # PEP 561 marker
```

---

## 5. Hello world (60-second quickstart)

This is the smallest possible working pipeline. It exists to anchor the docs
and as a smoke test that the API actually feels good for first-time users.

**`hello/schemas.py`**
```python
from pydantic import BaseModel

class Greeting(BaseModel):
    message: str
    language: str
```

**`hello/greet.j2`**
```jinja2
Greet a person named {{ ctx.name }} in {{ ctx.language | default("English") }}.
Return JSON with exactly two fields:
  - "message": a friendly one-line greeting
  - "language": the language you used
```

**`hello/pipeline.yaml`**
```yaml
models:
  default:
    provider: openai_compat
    base_url: ${OPENAI_BASE_URL}
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o-mini
    timeout:  60

steps:
  - name: greet
    type: llm
    model: default
    prompt: hello/greet.j2
    schema: hello.schemas:Greeting
    max_attempts: 3        # 1 initial + up to 2 self-correcting retries
```

**`hello/run.py`**
```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("hello/pipeline.yaml")
result = runner.run({"name": "Ada", "language": "French"})

if result.failed:
    print("Pipeline failed:", result.failure_state)
else:
    greeting = result.steps["greet"]      # already a Greeting instance
    print(greeting.message)
    print(greeting.language)
```

That's the whole API surface for a single-step extraction. Everything else
in this document — parallel steps, reviewers, vocab fields, batches — builds
on the same three files.

---

## 6. Core API

### 6.1 Running a pipeline

```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("pipeline.yaml")

result = runner.run({
    "document": "Full text of the paper…",
    "doi": "10.1000/xyz123",
    "config": my_config,        # any object; accessed as ctx.config in YAML
})

if not result.failed:
    print(result.steps["finalize"])
```

### 6.2 Batch processing

```python
from pyconveyor import BatchRunner

batch = BatchRunner("pipeline.yaml", max_workers=4)

for item_id, rctx in batch.run(items, key="doc_id"):
    if rctx.failed:
        log_failure(item_id, rctx.failure_state)
    else:
        save(item_id, rctx.steps["extract"])
```

`BatchRunner` wraps `PipelineRunner` with configurable concurrency, an
optional `tqdm` progress bar, and streaming results as they complete.

### 6.3 LLM utilities (standalone)

All LLM utilities are importable independently for scripts that don't need
the full pipeline runner:

```python
from pyconveyor.llm import make_client, call_llm, probe_json_mode, extract_json
from pyconveyor.prompt import render_prompt

client = make_client(base_url="https://api.openai.com/v1", api_key="sk-…")
supported = probe_json_mode(client, "gpt-4o", timeout=30)

prompt = render_prompt("prompts/", "extraction_v1.j2", document=text)
raw = call_llm(client, [{"role": "user", "content": prompt}],
               "gpt-4o", timeout=120, json_mode=supported)
data = extract_json(raw)
```

### 6.4 Failure introspection

When a step exhausts its retries, users need fast access to what went wrong
without digging through `metadata["attempt_logs"]`. The `RunContext` exposes
this directly:

```python
result = runner.run(input_data)

if result.failed:
    failed_step = result.failure_state.step_name      # "extract"
    last = result.steps[failed_step].last_attempt

    print(last.raw_output)        # the model's final raw response
    print(last.errors)            # list of structured error objects
    print(last.error_type)        # "schema_error" | "parse_error" | "timeout" | ...
    print(last.attempt_number)    # which attempt this was (1-indexed)
    print(last.elapsed_seconds)   # wall-clock for this attempt
```

`last_attempt` is also populated on **successful** steps for observability —
e.g. inspecting the prompt that worked, or measuring how many retries a
schema-feedback loop typically needs in production.

The full attempt history is still available at `rctx.steps["extract"].attempts`
(list of all attempts in order).

### 6.5 Pipeline visualisation

```python
from pyconveyor import generate_mermaid
print(generate_mermaid("pipeline.yaml"))
```

```bash
pyconveyor visualise pipeline.yaml --output pipeline.md
```

---

## 7. Expression safety (important design decision)

The current PlasticDB implementation evaluates `{{ expr }}` values with
Python's `eval()` behind a thin sandbox (`__builtins__: {}`). This works
in practice but has two real problems:

**Security.** If pipeline YAML ever comes from an untrusted source, `eval()`
is dangerous even with builtins stripped. AST traversal can escape the
sandbox in subtle ways.

**Debuggability.** When an expression fails, the error is a raw Python
exception with no reference to the YAML file or line number.

### Chosen approach: whitelisted AST evaluation

pyconveyor keeps the `{{ }}` delimiter (zero migration cost from PlasticDB)
but runs the inner expression through a strict AST whitelist before any
evaluation occurs. Only these node types are permitted:

- Attribute access (`steps.extract.primary`)
- Item lookup (`ctx["key"]`)
- Boolean operators (`and`, `or`, `not`)
- Comparison operators (`==`, `!=`, `is`, `is not`, `in`, `not in`)
- Ternary expressions (`x if cond else y`)
- String and numeric literals
- `None`, `True`, `False`
- Calls to an explicit allowlist of named helpers (`first_non_none`,
  `active_models`, `len`)

Any expression containing an AST node outside this set raises
`ExpressionSecurityError` at **pipeline load time** — before any run
begins — with the file name, YAML key path, and offending expression in
the message.

This makes the security boundary explicit, auditable (the whitelist is a
short list in `expr.py`), and extensible without opening `eval()` further.

---

## 8. YAML ergonomics

YAML pipelines become painful when errors are cryptic. This is treated as a
first-class concern from v0.1, not an afterthought added later.

### 8.1 Rich validation errors with "did you mean?" suggestions

`pyconveyor validate` and pipeline load both produce errors with the file
name, YAML line number, key path, plain-English description, and — for
common typos — a suggested fix:

```
pipeline.yaml:34  steps[2].inputs.primary
  Expression error: 'step' is not a valid root.
  Did you mean: 'steps'?

pipeline.yaml:41  steps[3].model
  Reference error: model 'reviewr' is not defined in the models: block.
  Did you mean: 'reviewer'?
  Defined models: primary, reviewer

pipeline.yaml:58  steps[5].fn
  Import error: 'myproject.steps:reconcil' is not importable.
  Did you mean: 'myproject.steps:reconcile'?
```

Suggestions use string-distance scoring against the set of valid alternatives
(known step names, defined models, importable callables in the target
module). They are best-effort: when no good candidate exists, the error
shows the available options instead.

Checks run at load time, before any API call:
- All `fn:` references resolve to importable callables.
- All `model:` references exist in the `models:` block.
- All `parser:` references exist in the `parsers:` block.
- All `schema:` references resolve to a Pydantic `BaseModel` subclass.
- All `{{ expr }}` expressions pass AST whitelist validation.
- All step name references in expressions point to defined steps.
- Required fields present on every step.
- No duplicate step names.

### 8.2 JSONSchema export for editor autocomplete

```bash
pyconveyor schema > pyconveyor-schema.json
```

Outputs a JSONSchema document for the pipeline YAML format. Users point VS
Code's `yaml.schemas` setting at it for inline autocomplete and validation:

```json
// .vscode/settings.json
{
  "yaml.schemas": {
    "./pyconveyor-schema.json": "pipeline.yaml"
  }
}
```

`pyconveyor init` (see §14) generates this `.vscode/settings.json` for the
user automatically.

### 8.3 SCHEMA.md as a public contract

A standalone `SCHEMA.md` in the repo root documents every supported YAML
field: type, whether required, default value, and a one-line example.
Changes to it require a changelog entry and follow the versioning policy.

### 8.4 Logging configuration

pyconveyor uses the standard `logging` module under the `pyconveyor` logger
namespace (`pyconveyor.runner`, `pyconveyor.llm`, `pyconveyor.cache`, etc.).
Users configure verbosity through Python's normal logging API:

```python
import logging
logging.getLogger("pyconveyor").setLevel(logging.DEBUG)
```

Three log levels, each chosen to match what users actually want to see:

| Level | What you get |
|---|---|
| `WARNING` (default) | Retries, schema validation failures, cache misses on a step that expected a hit |
| `INFO` | Per-step start/end, model selection, attempt count, token usage when reported |
| `DEBUG` | Full prompts, full responses, every cache key, expression evaluation traces |

**Sensitive content.** At `DEBUG` level, prompts and responses are logged
verbatim. This may include API keys baked into prompts by mistake, PII
in input documents, and customer data. The logger emits a one-time warning
when `DEBUG` is enabled. Production users should keep logging at `INFO` or
above and rely on the structured `RunContext.summary()` for observability
(see §12.7) rather than log scraping.

`pyconveyor run --verbose` and `--quiet` map to `DEBUG` and `ERROR`
respectively.

---

## 9. YAML pipeline format

```yaml
# my_pipeline.yaml

models:
  primary:
    provider: openai_compat           # openai_compat | anthropic | mock
    base_url: ${OPENAI_BASE_URL}
    api_key:  ${OPENAI_API_KEY}
    model:    ${MODEL_NAME}
    timeout:  120
    required: true

  reviewer:
    provider: openai_compat
    base_url: ${REVIEWER_BASE_URL}
    api_key:  ${REVIEWER_API_KEY}
    model:    ${REVIEWER_MODEL}
    timeout:  120
    required: false          # pipeline continues if reviewer not configured

parsers:
  extraction: myproject.parsers:parse_extraction

steps:
  - name: extract
    type: parallel
    steps:
      - name: primary
        type: llm
        model: primary
        prompt: extraction_v1.j2
        vars:
          document: "{{ ctx.document }}"
        schema: myproject.schemas:ExtractionResult
        parser: extraction
        max_attempts: 3
        retry_hint: "Return only a JSON object. No markdown fences."

      - name: reviewer
        type: llm
        model: reviewer
        prompt: extraction_v1.j2
        vars:
          document: "{{ ctx.document }}"
        schema: myproject.schemas:ExtractionResult
        parser: extraction
        required: false

  - name: reconcile
    type: transform
    fn: myproject.steps:reconcile
    inputs:
      primary:  "{{ steps.extract.primary }}"
      reviewer: "{{ steps.extract.reviewer }}"
    condition: "{{ steps.extract.primary is not none and steps.extract.reviewer is not none }}"
    required: false
    on_error: continue                  # see §9.2

  - name: finalize
    type: io
    fn: myproject.steps:save_result
    inputs:
      result: "{{ first_non_none(steps.reconcile, steps.extract.primary) }}"
      doc_id: "{{ ctx.doi }}"
    on_failure: myproject.steps:log_failure_to_db    # see §9.2
```

### 9.1 Step types

| Type | Meaning |
|---|---|
| `llm` | Render prompt → call model → parse response → validate against schema |
| `transform` | Pure function, no side effects |
| `validate` | Gate: raises to abort the pipeline on failure |
| `io` | Side effects (file writes, DB calls, network) |
| `parallel` | Run child steps concurrently; result is `{name: result}` |
| `condition` | Evaluate `if:` → run `then:` or `else:` branch |

### 9.2 Step-level `on_error` and `on_failure`

Two independent hooks control what happens when a step exhausts its retries:

| Field | Type | Meaning |
|---|---|---|
| `on_error` | `"raise"` (default) \| `"continue"` \| `"skip_remaining"` | What the runner does next |
| `on_failure` | dotted callable, e.g. `myproject.steps:log_failure` | A function called with `(step_name, exception, rctx)` for side effects |

`on_error` controls control flow; `on_failure` runs side effects (logging,
metrics, DB writes). They are independent and can be combined:

```yaml
- name: optional_enrichment
  type: llm
  model: primary
  prompt: enrich.j2
  schema: myproject.schemas:Enrichment
  max_attempts: 2
  on_error: continue                              # don't kill the pipeline
  on_failure: myproject.steps:record_partial      # but do record what happened
```

Behaviour matrix:

| `on_error` | After failure |
|---|---|
| `raise` | Pipeline stops; `result.failed = True`; `failure_state` populated |
| `continue` | Step result is `None`; downstream steps run; `result.failed` remains `False` |
| `skip_remaining` | All later steps are skipped with status `skipped`; `result.failed = False` |

### 9.3 `schema:` vs `parser:` — when to use each

These two fields are commonly confused. They serve different purposes and
compose in a fixed order.

- **`parser:`** is a **transformation**. It takes the raw model response
  string and returns a Python object (typically a dict). Use it when the
  model returns something that needs reshaping before validation — for
  example, flattening a nested envelope, splitting a delimited list, or
  pulling a JSON object out of mixed prose. If absent, pyconveyor's
  built-in `extract_json` is used, which handles the common cases (fenced
  code blocks, prose around a JSON object, BOMs).
- **`schema:`** is **validation**. It points to a Pydantic `BaseModel`
  subclass that the parsed dict must conform to. The step's result is the
  validated model instance, not the raw dict. If absent, the parser's
  output is returned as-is (typically a plain dict).

**Order of operations on every `llm` step:**

```
raw_response (str)
  └─→ parser(raw_response)        # if parser: is set, else extract_json
      └─→ parsed (typically dict)
          └─→ Schema(**parsed)    # if schema: is set
              └─→ validated model instance  ← step result
```

Validation errors from `Schema(**parsed)` are what triggers the retry-with-
feedback loop in §10. Errors raised from the parser itself are treated as
parse errors (also covered in §10).

---

## 10. Validation feedback in retry loops

This is the feature that lets a model fix its own mistakes. Two failure
modes get unified treatment:

- **Parse error** — the response wasn't valid JSON at all (e.g. the model
  wrapped it in markdown fences with extra prose, or returned a partial
  truncation).
- **Schema error** — the response parsed, but violated the Pydantic schema
  (missing required field, wrong type, value outside a constraint).

Both feed the model's previous output back to it on the next attempt,
along with a description of what went wrong. Without this, retries are
essentially blind — the model gets the same prompt and tends to make the
same mistake.

### 10.1 How it works

When `error_feedback: true` and a retryable error is raised, pyconveyor
appends the previous attempt's output and a description of the failure
to the message history before the next call. The model sees its own prior
turn followed by a user message explaining what to fix.

For a schema error, the next attempt's user-facing feedback looks like:

```
Your previous response failed schema validation. Here is what you returned:

{
  "entries": [
    {"organism_name": "Ideonella sakaiensis", "plastic": "PET", "evidence": []}
  ]
}

Validation errors:
- entries[0].evidence: List must have at least 1 item.
- entries[0].confidence: Field required.

Please fix these issues and return a corrected JSON object.
```

For a parse error, it looks like:

```
Your previous response was not valid JSON:

```
Here is the extracted data:
{ "entries": [...]
```

Please return only a valid JSON object, with no surrounding prose or
markdown fences.
```

### 10.2 Conversation message structure (pinned)

The retry uses a true multi-turn conversation, not prompt mutation. After
the first failed attempt, the messages array sent to the model is:

```python
[
    {"role": "system",    "content": <original system prompt, if any>},
    {"role": "user",      "content": <original rendered prompt>},
    {"role": "assistant", "content": <previous raw response>},   # what the model said
    {"role": "user",      "content": <feedback block from §10.1>},
]
```

If `retry_hint` is also set, it is appended to the feedback block in the
final user message. This structure is identical for parse errors and
schema errors; only the feedback block content differs.

This matters because it lets the model see its own prior output adjacent
to the correction request — the same way a human reviewer would highlight
a mistake. Mutating the original system prompt (the obvious alternative)
hides the failed turn from the model and works less reliably in practice.

### 10.3 YAML configuration

```yaml
steps:
  - name: extract
    type: llm
    model: primary
    prompt: extraction_v1.j2
    schema: myproject.schemas:ExtractionResult
    parser: extraction

    max_attempts: 3                  # total budget: 1 initial + up to 2 feedback retries
    error_feedback: true             # default when schema: is set; explicit here
    retry_hint: "Return only a JSON object. No markdown fences."
```

| Field | Default | Meaning |
|---|---|---|
| `max_attempts` | `3` if `schema:` is set, else `1` | Total attempt budget |
| `error_feedback` | `true` if `schema:` is set, else `false` | Append previous output + error on retry |
| `retry_hint` | `""` | Static text appended to the feedback message on every retry |
| `schema_strict` | `true` | Raise on validation errors; `false` keeps partial output (see §10.6) |
| `retry_on` | `["parse", "schema"]` | Which error categories trigger a retry (see §10.5) |
| `max_feedback_tokens` | `4000` | Cap on previous-output bytes echoed back; truncates with marker |
| `error_template` | built-in | Custom Jinja2 template for the feedback message (see §10.7) |

`retry_hint` and `error_feedback` compose. The hint appears every retry;
the feedback block appears only when the error category is in `retry_on`.

### 10.4 Smart defaults so the feature actually fires

If a user sets `schema:` on an `llm` step but leaves `max_attempts` at the
old default of `1`, the entire feedback feature does nothing — the model
gets exactly one shot and there is no retry to feed back to. That is a
usability trap.

**Defaults are conditional on whether `schema:` is set:**

| Setting | `schema:` absent | `schema:` present |
|---|---|---|
| `max_attempts` | `1` | `3` |
| `error_feedback` | `false` | `true` |

Both can be overridden per-step. A user who explicitly wants single-shot
schema validation can set `max_attempts: 1` and the warning is silenced.

The runner emits a one-line `INFO` log at load time describing the
effective retry policy for each `llm` step, so the actual behaviour is
never hidden.

### 10.5 `retry_on` — granular control over which errors retry

Some users want to retry on schema errors but fail-fast on timeouts (or
vice versa). `retry_on` makes this explicit:

```yaml
- name: extract
  type: llm
  schema: myproject.schemas:ExtractionResult
  max_attempts: 3
  retry_on: [schema, parse]        # default; timeouts and HTTP errors fail fast
```

Available categories:

| Category | Triggers on |
|---|---|
| `schema` | Pydantic `ValidationError` from `Schema(**parsed)` |
| `parse` | Parser raised, or response wasn't valid JSON |
| `timeout` | Request exceeded `timeout` seconds |
| `http_error` | Provider returned 5xx (4xx other than 429 fails fast) |
| `rate_limit` | Provider returned 429 |
| `low_confidence` | Custom: parsed result's `confidence` field below a threshold |

The default `[schema, parse]` matches the most common case: retry when the
output is malformed, but don't burn budget on infrastructure failures.

### 10.6 `schema_strict: false` — partial output mode

The default behaviour treats any Pydantic `ValidationError` as a failure.
For some extraction tasks — e.g. pulling 50 records from a paper, where
losing 2 to a bad field shouldn't kill the other 48 — a non-strict mode
is more useful:

```yaml
- name: extract
  type: llm
  schema: myproject.schemas:ExtractionResult
  schema_strict: false       # validation errors logged, not raised
```

In non-strict mode:

- Pydantic errors are recorded in the step's `last_attempt.errors` and in
  `rctx.summary().validation_warnings`.
- The step's result is the **parsed dict**, not a validated model instance
  (because validation didn't pass). Downstream steps must handle this.
- No retry is triggered for schema errors specifically — the result is
  accepted as-is. Parse errors still retry per `retry_on`.

This is intentionally a non-default, opt-in mode. The strict default is
the right behaviour for most pipelines.

### 10.7 Custom error template

The default feedback messages are intentionally plain English. To override:

```yaml
- name: extract
  type: llm
  schema: myproject.schemas:ExtractionResult
  max_attempts: 3
  error_template: prompts/retry_feedback.j2
```

```jinja2
{# prompts/retry_feedback.j2 #}
{% if error_type == "schema" %}
PREVIOUS OUTPUT (invalid):
{{ previous_output }}

VALIDATION ERRORS:
{% for error in errors %}
- {{ error.loc_str }}: {{ error.msg }}
{% endfor %}

Return corrected JSON only.
{% elif error_type == "parse" %}
PREVIOUS OUTPUT (not valid JSON):
{{ previous_output }}

Return only a valid JSON object. No prose, no markdown fences.
{% endif %}
```

Template variables:

| Variable | Type | Available when |
|---|---|---|
| `error_type` | `"schema"` \| `"parse"` | always |
| `previous_output` | `str` | always (raw model response) |
| `errors` | `list[ErrorInfo]` with `loc_str`, `msg`, `type` | `error_type == "schema"` |
| `parse_error_message` | `str` | `error_type == "parse"` |
| `attempt` | `int` | always (1-indexed, the attempt about to start) |
| `retry_hint` | `str` | always (may be empty) |

### 10.8 Token budget for retries

Each retry echoes the previous output back into the message history. For
long extractions, attempt 3 can be 3× the original prompt. `max_feedback_tokens`
caps how much previous output is included; anything beyond it is truncated
with a `[…truncated for length…]` marker.

```yaml
- name: extract
  type: llm
  schema: myproject.schemas:ExtractionResult
  max_attempts: 3
  max_feedback_tokens: 4000        # default
```

This is independent from the model-level `max_tokens` (which caps the
*response*) and from `max_prompt_tokens` (§12.8, which caps the whole
outgoing message).

### 10.9 Attempt sequence example

For `max_attempts: 3` with default `error_feedback: true`:

```
Attempt 1:  [system, user(prompt)]
            → ValidationError: entries[0].confidence field required

Attempt 2:  [system, user(prompt), assistant(prev_output_1), user(feedback_1)]
            → ValidationError: entries[0].evidence must have ≥ 1 item

Attempt 3:  [system, user(prompt), assistant(prev_output_2), user(feedback_2)]
            → Success: valid ExtractionResult returned
```

If all attempts are exhausted, the step raises and `on_error` / `on_failure`
handling takes over per §9.2.

### 10.10 Attempt log entries

Every attempt (success or failure) is recorded in `rctx.metadata["attempt_logs"]`:

```python
[
  {"step": "extract", "attempt": 1, "status": "schema_error",
   "errors": ["entries[0].confidence: Field required"],
   "elapsed_seconds": 2.3, "tokens": {"prompt": 1200, "completion": 340}},
  {"step": "extract", "attempt": 2, "status": "schema_error",
   "errors": ["entries[0].evidence: List must have at least 1 item"],
   "elapsed_seconds": 2.1, "tokens": {"prompt": 1810, "completion": 360}},
  {"step": "extract", "attempt": 3, "status": "success",
   "elapsed_seconds": 1.9, "tokens": {"prompt": 2380, "completion": 350}},
]
```

Possible `status` values:

| Status | Cause |
|---|---|
| `success` | Step completed; schema validated |
| `schema_error` | Pydantic `ValidationError`; fed back per `error_feedback` |
| `parse_error` | Response wasn't valid JSON; fed back per `error_feedback` |
| `low_confidence` | Confidence below threshold (when configured) |
| `timeout` | Request exceeded timeout |
| `http_error` | Provider 5xx |
| `rate_limit` | Provider 429 |
| `error` | Other exception |

---

## 11. Vocabulary-constrained fields

This is a first-class feature, not a user responsibility. Many extraction
pipelines have fields that should draw from a controlled vocabulary — plastic
types, evidence methods, isolation environments — but where the LLM may
legitimately encounter terms the vocabulary doesn't yet cover.

The naive approaches both fail:
- **Hard enum validation** rejects valid novel terms and causes extraction failures.
- **No validation** lets garbage values silently corrupt the output.

pyconveyor's `VocabField` sits between these: it normalises to the closest
known term when possible, but preserves the LLM's raw suggestion alongside it
so a human can decide whether the vocabulary needs to grow.

### 11.1 How it works

Every `VocabField` produces two values in the extracted record:

```python
from pyconveyor.vocab import VocabField, Vocabulary

PlasticVocab = Vocabulary(
    known={"PET", "PE", "PLA", "PCL", "PHA", "PHB", "PU", "PVA", "PBS"},
    label="plastic_type",
)

class ExtractionRecord(BaseModel):
    plastic: str = VocabField(vocab=PlasticVocab)
    # automatically adds:
    # plastic_novel: str | None  — raw LLM value when not in vocab
    # plastic_vocab_match: bool  — True when value was in known set
```

The validator logic per field:

1. If the LLM value is in `known` → store it as-is; `_novel = None`;
   `_vocab_match = True`.
2. If it is close to a known term (edit-distance or substring heuristic)
   → store the canonical match; `_novel = <raw LLM value>`; `_vocab_match = False`.
3. If it is genuinely unknown → store the raw LLM value unchanged;
   `_novel = <raw LLM value>`; `_vocab_match = False`.

Cases 2 and 3 both surface in the run summary's `vocab_suggestions` list so
they can be reviewed without combing through raw JSON.

### 11.2 YAML vocabulary definitions

Vocabularies can be defined inline in the pipeline YAML so they live
alongside the pipeline that uses them:

```yaml
vocabularies:
  plastic_type:
    known:
      - PET
      - PE
      - PLA
      - PCL
      - PHA
      - PHB
      - PU
      - PVA
      - PBS
    fuzzy_match: true     # enable edit-distance normalisation (default: true)
    case_sensitive: false # default: false

  evidence_method:
    known:
      - Weight loss
      - FTIR
      - SEM
      - NMR
      - GC
      - HPLC
      - CO2
    fuzzy_match: true
```

Or loaded from a separate file (easier to version independently):

```yaml
vocabularies:
  plastic_type:
    file: config/vocab/plastic_types.yaml
  evidence_method:
    file: config/vocab/evidence_methods.yaml
```

### 11.3 Vocab suggestions in the run summary

```python
s = rctx.summary()
for suggestion in s.vocab_suggestions:
    print(suggestion.field)        # "plastic"
    print(suggestion.raw_value)    # "poly(ethylene terephthalate)"
    print(suggestion.matched_to)   # "PET"  (or None if no match found)
    print(suggestion.match_type)   # "fuzzy" | "exact" | "novel"
    print(suggestion.doi)          # provenance
```

`BatchRunner` aggregates these across all items so you get a single report
of all novel terms seen across a full batch run — exactly what you need to
decide whether to extend the vocabulary after a daily run.

### 11.4 Prompt injection

`VocabField` can also inject the known terms into the prompt automatically,
so the LLM knows what the preferred vocabulary looks like:

```jinja2
Extract the plastic type. Use one of the known values if applicable:
{{ vocab.plastic_type.known | join(", ") }}
If none fit, propose the most accurate term you can.
```

The `vocab` variable is available in all Jinja2 templates when vocabularies
are defined.

---

## 12. Model configuration and observability

The current PlasticDB model config only covers `base_url`, `api_key`, and
`model`. pyconveyor exposes the full set of parameters you'd want to tune
in production.

### 12.1 Full YAML model block

```yaml
models:
  primary:
    provider: openai_compat
    base_url:    ${MODEL_A_BASE_URL}
    api_key:     ${MODEL_A_API_KEY}
    model:       ${MODEL_A}
    timeout:     300
    required:    true

    # Sampling parameters
    temperature: 0.1          # default: provider default (usually 1.0)
    top_p:       0.95         # optional
    max_tokens:  4096         # optional; caps the response length
    seed:        42           # optional; for reproducible outputs when supported

    # Retry behaviour for HTTP-level failures (separate from §10 retries)
    max_retries: 3            # 429/5xx retries (default: 2)
    retry_delay: 2.0          # seconds between retries (default: 1.0)

    # Cost accounting (see §12.7)
    pricing:
      input_per_1k:  0.0025   # USD per 1k input tokens
      output_per_1k: 0.0100   # USD per 1k output tokens

    # Extra params passed through to the API verbatim
    extra_params:
      reasoning_effort: high  # e.g. for Claude extended thinking or o1 variants
```

All sampling parameters can also be overridden at the **step level**, so
you can use a low temperature for the primary extraction pass and a higher
one for a creative reconciliation step:

```yaml
steps:
  - name: extract
    type: llm
    model: primary
    temperature: 0.0          # deterministic; overrides model-level setting
    prompt: extraction_v1.j2
    ...

  - name: reconcile_llm
    type: llm
    model: primary
    temperature: 0.4          # more exploratory for the merge step
    prompt: reconciliation_v1.j2
    ...
```

### 12.2 Programmatic override

API keys and sampling params can be passed in code rather than via env
vars — useful for multi-tenant applications or testing:

```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("pipeline.yaml")

result = runner.run(
    input_data,
    model_overrides={
        "primary": {
            "api_key":     "sk-...",
            "temperature": 0.0,
            "max_tokens":  2048,
        }
    }
)
```

Overrides are merged on top of the YAML definition at run time; they never
mutate the loaded pipeline spec, so the same `runner` instance is safe to
reuse with different overrides.

### 12.3 Provider abstraction

Built-in providers:

| Provider string | Backend |
|---|---|
| `openai_compat` (default) | `openai.OpenAI` — works with OpenAI, Ollama, vLLM, LM Studio, any proxy |
| `anthropic` | `anthropic.Anthropic` (native SDK) |
| `mock` | Returns a configured fixed string; for unit tests without API calls |

Custom providers register with a decorator:

```python
from pyconveyor import register_provider

@register_provider("my_backend")
def make_my_client(base_url, api_key, **kwargs):
    return MyClient(base_url, api_key)
```

### 12.4 Hooks

```python
runner = PipelineRunner("pipeline.yaml")

@runner.on_step_end
def log_end(step_name, result, rctx):
    metrics.increment("step.end", tags={"step": step_name})

@runner.on_llm_call
def record_tokens(step_name, model, response):
    metrics.histogram("llm.tokens", response.usage.total_tokens)
```

### 12.5 Response caching for development

Repeated runs with deterministic settings (`temperature: 0`, fixed `seed`)
during development burn tokens for no benefit. Opt-in caching at the model
level fixes this:

```yaml
models:
  primary:
    provider: openai_compat
    model:    gpt-4o
    temperature: 0.0
    seed:     42
    cache:
      enabled: true
      dir:     .pyconveyor-cache
      ttl_days: 7              # optional; default: no expiry
```

The cache key is a hash of `(provider, model, full message array, sampling params)`.
A hit returns the stored response without an API call. Cache directories
should be `.gitignore`d.

Three control knobs:

| Override | Effect |
|---|---|
| `cache.enabled: false` (YAML) | Disable caching for this model |
| `runner.run(..., use_cache=False)` | Bypass cache for this run; still writes new responses |
| `runner.run(..., refresh_cache=True)` | Ignore stored responses; overwrite on success |

The cache is intentionally simple — file-per-key under `dir/` — so it can
be inspected and selectively deleted with `rm`. There is no eviction beyond
TTL; users running many distinct prompts should clear the directory
periodically. **Caching is for development. Never enable it in production
where input documents are the source of truth.**

A one-time `WARNING` log fires the first time a cache is hit during a run
so users don't accidentally ship code that's silently using stale responses.

### 12.6 Dry-run mode

```python
result = runner.run(data, dry_run=True)
# LLM steps return None; script steps still execute
```

Validates pipeline logic and expression correctness before spending tokens.

### 12.7 Structured run summary

```python
s = rctx.summary()
# s.steps_run: list[str]
# s.steps_failed: list[str]
# s.steps_skipped: list[str]
# s.llm_calls: int
# s.total_tokens: TokenCount   (input, output, total — when provider exposes usage)
# s.cost_estimate: CostEstimate | None   (USD — when model `pricing:` is configured)
# s.elapsed_seconds: float
# s.attempt_logs: list[AttemptLog]
# s.validation_warnings: list[ValidationWarning]   (from schema_strict: false)
# s.vocab_suggestions: list[VocabSuggestion]
# s.cache_hits: int
# s.cache_misses: int
```

`cost_estimate` is `None` unless the model's `pricing:` block is set. When
present it exposes `s.cost_estimate.usd` (a `Decimal`) and per-model
breakdowns at `s.cost_estimate.per_model`. `BatchRunner` aggregates these
across all items.

### 12.8 Token budget guard

```yaml
steps:
  - name: extract
    type: llm
    model: primary
    prompt: extraction_v1.j2
    max_prompt_tokens: 120000    # raises PromptTooLargeError or truncates with warning
```

Prevents silent truncation by the API; the behaviour (raise vs. truncate)
is configurable per step.

---

## 13. Defaults reference

A consolidated table of every default in pyconveyor. Source of truth lives
in `SCHEMA.md`; this is mirrored here so AI agents implementing the package
have a single place to verify against.

### Model block

| Field | Default | Notes |
|---|---|---|
| `provider` | `openai_compat` | |
| `timeout` | `120` (seconds) | |
| `required` | `true` | |
| `temperature` | provider default | usually `1.0` for OpenAI |
| `top_p` | unset | not sent to API |
| `max_tokens` | unset | not sent to API |
| `seed` | unset | |
| `max_retries` | `2` | HTTP-level retries on 429/5xx |
| `retry_delay` | `1.0` (seconds) | |
| `cache.enabled` | `false` | |
| `cache.dir` | `.pyconveyor-cache` | when enabled |
| `cache.ttl_days` | unset (no expiry) | |

### LLM step

| Field | Default | Notes |
|---|---|---|
| `max_attempts` | `3` if `schema:` set, else `1` | conditional default (§10.4) |
| `error_feedback` | `true` if `schema:` set, else `false` | conditional default |
| `retry_hint` | `""` | |
| `retry_on` | `["parse", "schema"]` | |
| `schema_strict` | `true` | |
| `max_feedback_tokens` | `4000` | |
| `error_template` | built-in | |
| `parser` | built-in `extract_json` | |
| `required` | `true` | |
| `on_error` | `raise` | |
| `on_failure` | unset | |
| `max_prompt_tokens` | unset | no guard |

### Vocabulary

| Field | Default |
|---|---|
| `fuzzy_match` | `true` |
| `case_sensitive` | `false` |

### BatchRunner

| Field | Default |
|---|---|
| `max_workers` | `4` |
| `progress` | `true` if `tqdm` installed, else `false` |
| `key` | `"id"` |

---

## 14. CLI reference

### 14.1 `pyconveyor init`

Bootstrap a working pipeline in one command. Generates:

- `pipeline.yaml` — minimal one-step pipeline using `${OPENAI_API_KEY}`
- `prompts/extract.j2` — example prompt
- `schemas.py` — example Pydantic schema
- `steps.py` — example transform step
- `.vscode/settings.json` — pre-pointed at the JSONSchema export
- `pyconveyor-schema.json` — initial export
- `.gitignore` entries for `.pyconveyor-cache/` and `.env`

```bash
pyconveyor init my_pipeline/
cd my_pipeline/
pyconveyor run pipeline.yaml --input '{"document": "..."}'
```

The generated pipeline is intentionally trivial — one `llm` step with a
schema and `max_attempts: 3` — so it both works out of the box and
demonstrates the most important feature.

### 14.2 `pyconveyor run`

```bash
pyconveyor run pipeline.yaml \
    --input input.json \
    --output result.json \
    [--dry-run] [--no-cache] [--refresh-cache] [--verbose] [--quiet]
```

`--input` accepts a path to a JSON file or `-` for stdin.

### 14.3 `pyconveyor validate`

```bash
pyconveyor validate pipeline.yaml
```

Runs every load-time check from §8.1 and prints errors with file/line
context. Exits non-zero on any failure.

### 14.4 `pyconveyor schema`

```bash
pyconveyor schema > pyconveyor-schema.json
```

Emits the JSONSchema document for the YAML pipeline format.

### 14.5 `pyconveyor visualise`

```bash
pyconveyor visualise pipeline.yaml --output pipeline.md
```

Produces a Mermaid DAG. Output is a Markdown file with the diagram embedded.

---

## 15. Testing strategy

### Unit tests (no API calls)

- Use the `mock` provider for all LLM steps.
- Test expression AST whitelist, condition branching, parallel merging,
  retry logic, error feedback message construction, `on_error`/`on_failure`
  handling, vocab matching, cache hit/miss, and "did you mean?" suggestions
  independently.
- `tests/fixtures/pipelines/` holds small YAML files covering every step
  type and control-flow pattern. These double as documentation examples.
- A dedicated test fixture for §10: `mock` provider configured to return
  a sequence of bad-JSON, schema-invalid, then valid responses, asserting
  the message array sent on each retry matches §10.2 exactly.

### Integration tests (real API, opt-in)

- Gated behind `PYCONVEYOR_INTEGRATION_TESTS=1`.
- Skipped in CI unless the env var and a real API key are present.

---

## 16. Documentation plan

| Page | Content |
|---|---|
| README | 5-minute quickstart from §5; install; hello-world pipeline |
| Concepts | Pipeline → Steps → Context data flow; the determinism philosophy |
| YAML reference (SCHEMA.md) | Every field, type, default, example |
| Defaults reference | Mirror of §13 |
| Expression language | Allowed AST nodes; the whitelist; debugging tips |
| Validation feedback | How retry loops work; attempt log reading; custom error templates; conversation message structure |
| Step types guide | When to use transform vs. validate vs. io; `on_error`/`on_failure` |
| `schema:` vs `parser:` | The §9.3 explainer as a standalone page |
| LLM utilities | `make_client`, `call_llm`, `extract_json` standalone usage |
| Providers | OpenAI, Anthropic, Ollama, mock, custom |
| BatchRunner | Batch processing, concurrency, streaming |
| Hooks | Observability, metrics integration |
| Caching | Development cache; cache control; production warning |
| Logging | Levels, sensitive-content note, production guidance |
| Cost tracking | `pricing:` block; summary fields; per-model attribution |
| Visualisation | `generate_mermaid`, `pyconveyor visualise` |
| Editor setup | JSONSchema autocomplete in VS Code and others |
| Vocabulary fields | Defining vocabs in YAML; VocabField usage; reading vocab suggestions |
| Migrating from PlasticDB | 5-step import swap; zero YAML changes |
| Examples | Single-step extraction; dual-model reconciliation; multi-stage research pipeline |

Host on **Read the Docs** (auto-built from `docs/` on every tag).

---

## 17. Packaging

```toml
[project]
name = "pyconveyor"
version = "0.1.0"
description = "Deterministic YAML pipeline engine for structured LLM extraction"
requires-python = ">=3.10"

dependencies = [
    "openai>=1.0",
    "jinja2>=3.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
anthropic = ["anthropic>=0.25"]
progress  = ["tqdm>=4.0"]
dev       = ["pytest", "pytest-cov", "ruff", "mypy"]

[project.scripts]
pyconveyor = "pyconveyor.cli:main"

[project.urls]
Repository    = "https://github.com/your-org/pyconveyor"
Documentation = "https://pyconveyor.readthedocs.io"
Changelog     = "https://github.com/your-org/pyconveyor/blob/main/CHANGELOG.md"
```

### Release workflow (GitHub Actions)

```
on: push to tag v*.*.*
  → ruff lint + mypy
  → pytest (unit only; integration skipped)
  → build sdist + wheel
  → publish to PyPI via Trusted Publisher (OIDC — no stored secrets)
  → create GitHub Release with changelog excerpt
```

---

## 18. Versioning policy

The YAML pipeline format is treated as a **public API** subject to the same
semver rules as the Python API:

- **Patch**: bug fixes; no schema or Python API changes.
- **Minor**: new features backwards-compatible with existing YAML files.
  New optional fields, new step types, new CLI commands.
- **Major**: any field rename or removal; any breaking Python API change.
  A migration guide is required in the changelog.

---

## 19. Scope boundaries (permanent)

These are not on a roadmap. They are off the roadmap by design.

- **No agents or tool calling.** This is an extraction engine. The moment
  it tries to be an agent framework too, it loses its identity.
- **No state machine / database.** pyconveyor processes one item per run.
  Your application decides what queue feeds it and what persistence stores
  the results.
- **No PDF/Markdown conversion, harvesting, or literature search.**
- **No async runtime.** Parallel steps use `ThreadPoolExecutor`. This is
  the right trade-off for simplicity. Async is not planned.
- **No GUI or web dashboard.** Mermaid is the visualisation layer.
- **No plugin marketplace or hub.** Composability comes from plain Python
  imports, not a platform.
- **No production cache.** The §12.5 cache is a development tool only.
  pyconveyor will never ship a distributed/shared/Redis cache.

The goal is to remain comprehensible in one sitting.

---

## 20. Migration path from PlasticDB

1. `pip install pyconveyor`
2. In `extractor.py`: replace `from src.pipeline_runner import PipelineRunner`
   with `from pyconveyor import PipelineRunner`
3. Replace `from src.llm_utils import …` with `from pyconveyor.llm import …`
4. Delete `src/pipeline_runner.py` and `src/llm_utils.py`
5. Replace `StageRunner` usage with `BatchRunner` or a direct loop over
   `PipelineRunner.run()`

`pipeline/extraction.yaml`, all step files, and all parsers are untouched.

The conditional defaults in §10.4 mean existing pipelines that set `schema:`
will gain free retry-with-feedback behaviour after the upgrade. If that's
not desired, set `max_attempts: 1` explicitly or `error_feedback: false`.

---

## 21. Milestones

| Milestone | Deliverables |
|---|---|
| **v0.1.0** | Core runner extracted from PlasticDB; AST-whitelisted expression evaluator with "did you mean?" suggestions; all existing step types; step-level `on_error`/`on_failure`; `mock` provider; full model config (temperature, max_tokens, seed, extra_params, programmatic overrides); unified parse + schema error feedback retry loop with conversation message structure pinned per §10.2; `retry_on`, `schema_strict`, `max_feedback_tokens`, `error_template`; smart conditional defaults; `last_attempt` accessor on step results; logging configuration per §7.4; `pyconveyor init` CLI; unit test suite with fixture pipelines; README quickstart from §5; published to PyPI |
| **v0.2.0** | `BatchRunner`; `VocabField` + vocabulary YAML definitions + batch vocab suggestion report; dry-run mode; `pyconveyor validate` with line-number errors; `pyconveyor schema` JSONSchema export; SCHEMA.md; defaults reference page |
| **v0.3.0** | Native Anthropic provider; hooks API; `RunContext.summary()` with `cost_estimate`, `validation_warnings`, `cache_hits`/`cache_misses`; `pyconveyor visualise` CLI |
| **v0.4.0** | Token budget guard (`max_prompt_tokens`); response cache (§12.5); `first_non_none` helper; Read the Docs site live |
| **v1.0.0** | Stable YAML schema declared; full docs; editor setup guide; migration guide |
