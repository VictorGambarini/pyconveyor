# Step Types

pyconveyor has seven step types. Each serves a distinct role in the pipeline.

| Type | Purpose |
|---|---|
| `llm` | Call a language model, parse the response, validate against a schema |
| `ensemble` | Run N models in parallel, auto-judge and merge results |
| `transform` | Pure Python function — no side effects |
| `validate` | Gate: abort the pipeline if a condition isn't met |
| `io` | Side effects — file writes, database calls, network requests |
| `parallel` | Run child steps concurrently |
| `condition` | Branch on a runtime expression |

---

## `llm`

The core step type. Renders a Jinja2 prompt, calls a model, parses the response, and validates it against a Pydantic schema.

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema: schemas:ExtractionResult
    max_attempts: 3
```

### Key fields

| Field | Required | Description |
|---|---|---|
| `model` | yes | Name of a model defined in the `models:` block |
| `prompt` | yes | Path to a Jinja2 template (relative to the pipeline file) |
| `schema` | no | `module:ClassName` — a Pydantic `BaseModel` subclass |
| `parser` | no | `module:function` — transforms raw response before schema validation |
| `system` | no | System prompt string (not a template path) |
| `vars` | no | Extra variables injected into the prompt template |
| `max_attempts` | no | Total attempt budget (default: `3` if `schema:` set, else `1`) |
| `error_feedback` | no | Feed previous output back on retry (default: `true` if `schema:` set) |
| `retry_hint` | no | Static text appended to every retry feedback message |
| `on_error` | no | `raise` (default) \| `continue` \| `skip_remaining` |
| `on_failure` | no | `module:function` called with `(step_name, exception, rctx)` |

### `schema:` vs `parser:`

These serve different purposes and compose in a fixed order:

```
raw_response (str)
  └─→ parser(raw_response)     # if parser: set, else built-in extract_json
      └─→ parsed (typically dict)
          └─→ Schema(**parsed) # if schema: set
              └─→ validated model instance  ← step result
```

- **`parser:`** transforms the raw response string. Use it when the model returns something that needs reshaping before Pydantic sees it — flattening a nested envelope, splitting a delimited list, extracting JSON from mixed prose.
- **`schema:`** validates the parsed dict. The step's result is the validated model instance, not the raw dict.

When `schema:` is set and validation fails, pyconveyor retries and feeds the error back to the model. See [Validation Feedback](validation-feedback.md).

---

## `ensemble`

Runs N LLM members in parallel, then optionally runs a judge model to merge the results. This is the cleanest way to implement multi-model consensus extraction — no manual `parallel` + `transform` glue needed.

```yaml
steps:
  - name: extract
    type: ensemble
    schema: schemas:Record
    prompt: prompts/extract.j2
    members:
      - model: gpt4o
      - model: claude
        required: false
    judge:
      model: gpt4o
      condition: all_succeeded
```

### How it works

1. All members run in parallel (thread pool, one thread per member)
2. If `judge:` is set and its condition is met, the judge sees all member outputs and returns a merged result
3. If the judge is skipped (condition not met, or only one member succeeded) or fails, the first succeeded member's result is returned
4. If a required member fails, the pipeline aborts

### Key fields

| Field | Required | Description |
|---|---|---|
| `members` | yes | List of member definitions (at least one) |
| `prompt` | no | Jinja2 template shared by all members |
| `schema` | no | Pydantic model shared by all members and the judge |
| `judge` | no | Judge configuration (see below) |

Each member can override the shared prompt and add per-member LLM tuning fields (`temperature`, `max_attempts`, `vars`, etc.):

```yaml
members:
  - model: gpt4o
    name: primary
  - model: claude
    name: reviewer
    required: false
    prompt: prompts/extract_alt.j2    # override the shared prompt
    temperature: 0.0
    max_attempts: 2
```

### Judge configuration

| Field | Default | Description |
|---|---|---|
| `model` | required | Model key from the `models:` block |
| `condition` | `all_succeeded` | `all_succeeded` — judge runs only if every required member succeeded; `any_succeeded` — runs as long as two or more members succeeded |
| `prompt` | auto | Custom Jinja2 template for the judge. If omitted, the shared member prompt is extended with a built-in merge instruction |

The built-in judge prompt appends this to the rendered member prompt:

> The above prompt was sent independently to N model(s). Here are their outputs: [outputs]. Your task: Review all outputs carefully. Return a single merged JSON result that best represents the correct answer.

### Accessing individual member results

Each member's result is stored in `RunContext.steps` under `{ensemble_name}.{member_name}`:

```python
result = runner.run(input_data)
result.steps["extract"].value           # merged (judge or first-member fallback)
result.steps["extract.primary"].value   # gpt4o result
result.steps["extract.reviewer"].value  # claude result (None if failed)
```

Or in downstream step expressions:

```yaml
- name: audit
  type: transform
  fn: steps:compare
  inputs:
    primary:  "{{ steps.extract.primary }}"
    reviewer: "{{ steps.extract.reviewer }}"
```

### Fallback behaviour

| Situation | What happens |
|---|---|
| Judge runs and succeeds | Judge result is returned |
| Judge is skipped (condition not met, or only 1 succeeded) | First succeeded member result returned |
| Judge fails (parse error, timeout, etc.) | Logged as warning; first succeeded member result returned |
| A required member fails | `RuntimeError` raised; pipeline aborts |
| All optional members fail, no required members | `None` returned |

---

## `transform`

A pure Python function. No model call, no side effects.

```yaml
steps:
  - name: normalise
    type: transform
    fn: steps:normalise_text
    inputs:
      text: "{{ ctx.document }}"
```

```python
# steps.py
def normalise_text(text: str) -> str:
    return text.strip().lower()
```

The function receives the `inputs` dict as keyword arguments. Its return value becomes the step's result.

### `condition`

An optional expression that gates execution:

```yaml
- name: reconcile
  type: transform
  fn: steps:reconcile
  inputs:
    primary:  "{{ steps.extract.value }}"
    reviewer: "{{ steps.review.value }}"
  condition: "{{ steps.review.value is not none }}"
  on_error: continue
```

If `condition` evaluates to falsy, the step is skipped and its result is `None`.

---

## `validate`

A gate step. Raises and aborts the pipeline if the condition is not met.

```yaml
steps:
  - name: check_input
    type: validate
    condition: "{{ ctx.document is not none }}"
```

Use `validate` steps at the start of a pipeline to check required inputs, or between steps to assert invariants before spending tokens.

Unlike `condition` on a `transform` step (which just skips), a `validate` failure stops the pipeline with `result.failed = True`.

---

## `io`

A step that is explicitly allowed to have side effects. Structurally identical to `transform`, but signals intent.

```yaml
steps:
  - name: save
    type: io
    fn: steps:save_to_db
    inputs:
      result: "{{ steps.extract.value }}"
      doc_id: "{{ ctx.doc_id }}"
```

```python
# steps.py
def save_to_db(result, doc_id):
    db.insert(doc_id, result.model_dump())
```

`io` steps are intentionally last. The pipeline produces a result; the `io` step persists it. This keeps the runner's determinism guarantees intact for all earlier steps.

---

## `parallel`

Runs child steps concurrently using a thread pool. The result is a dict of `{child_name: child_result}`.

```yaml
steps:
  - name: extract
    type: parallel
    steps:
      - name: primary
        type: llm
        model: primary
        prompt: prompts/extract.j2
        schema: schemas:ExtractionResult

      - name: reviewer
        type: llm
        model: reviewer
        prompt: prompts/extract.j2
        schema: schemas:ExtractionResult
        required: false
```

Access child results:

```yaml
  - name: reconcile
    type: transform
    fn: steps:reconcile
    inputs:
      primary:  "{{ steps.extract.primary }}"
      reviewer: "{{ steps.extract.reviewer }}"
```

`required: false` on a child step means the pipeline continues even if that child fails. Its result will be `None`.

---

## `condition`

Branches based on a runtime expression.

```yaml
steps:
  - name: route
    type: condition
    if: "{{ ctx.mode == 'fast' }}"
    then:
      - name: quick_extract
        type: llm
        model: fast
        prompt: prompts/quick.j2
    else:
      - name: full_extract
        type: llm
        model: primary
        prompt: prompts/full.j2
        schema: schemas:ExtractionResult
```

Only one branch executes. Steps in the inactive branch have status `skipped`.

---

## `on_error` and `on_failure`

Two independent hooks control failure behaviour on any step:

| Field | Values | Effect |
|---|---|---|
| `on_error` | `raise` (default) | Pipeline stops; `result.failed = True` |
| `on_error` | `continue` | Step result is `None`; downstream steps run |
| `on_error` | `skip_remaining` | All later steps skipped; `result.failed = False` |
| `on_failure` | `module:function` | Called with `(step_name, exception, rctx)` for side effects |

`on_error` controls flow; `on_failure` runs side effects. They compose:

```yaml
- name: optional_enrichment
  type: llm
  model: primary
  prompt: prompts/enrich.j2
  schema: schemas:Enrichment
  max_attempts: 2
  on_error: continue
  on_failure: steps:record_partial_failure
```
