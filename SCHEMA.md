# Pipeline YAML Schema Reference

This document is the **public contract** for `pyconveyor` pipeline files.
Every field, its type, whether it's required, its default value, and an example are listed here.

---

## Top-level keys

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `models` | map | yes | — | Named model configurations (see [Model](#model)) |
| `steps` | list | yes | — | Ordered list of steps to execute |
| `schema` | map | no | — | Top-level YAML schema block (see [Schema block](#schema-block)) |
| `schemas` | map | no | — | Named schema imports (alternative to inline `schema:`) |
| `parsers` | map | no | — | Named parser imports |
| `vocabularies` | map | no | — | Named [Vocabulary](#vocabulary) definitions |
| `outputs` | map | no | — | Automatic output saving after a run (see [Outputs](#outputs)) |

---

## Schema block

Defined under the top-level `schema:` key. Generates a Pydantic model at load time. Fields are either simple type strings or rich dicts.

### Simple type string

```yaml
schema:
  name: str
  score: float | None
```

### Rich field dict

```yaml
schema:
  name:
    type: str
    description: "Full name of the entity."
    min_length: 1
  accession:
    type: str | None
    description: "Database accession ID."
    pattern: "^[A-Za-z0-9][A-Za-z0-9_.]{2,39}$"
    on_fail: null
```

### Rich field keys

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `type` | string | yes | — | Type string (see supported types above) |
| `description` | string | no | — | Rendered in `{{ schema_hint }}` prompt variable |
| `pattern` | string | no | — | Regex; value must match the full string |
| `min_length` | integer | no | — | Minimum string length |
| `max_length` | integer | no | — | Maximum string length |
| `min_items` | integer | no | — | Minimum list length |
| `max_items` | integer | no | — | Maximum list length |
| `on_fail` | string | no | `error` | `error` — raise (triggers retry); `null` — coerce to None; `warn` — log and keep |
| `vocab` | string | no | — | Key from `vocabularies:` block; hint only, not enforced |

### Nested list of objects

```yaml
schema:
  entries:
    type: list
    description: "One entry per record."
    min_items: 1
    items:
      organism:
        type: str
        description: "Genus + species binomial."
        min_length: 1
      confidence:
        type: float
        description: "Extraction confidence 0.0–1.0."
```

### Supported type strings

`str`, `int`, `float`, `bool`, any of the above followed by ` | None`, and `list[str]` / `list[int]` / `list[float]` / `list[bool]` / `dict[str, str]` / `dict[str, int]`. Use `type: list` with an `items:` block for lists of structured objects.

---

## Model

Defined under `models.<name>`:

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `provider` | string | yes | — | One of `openai_compat`, `anthropic`, `mock`, or a registered custom name |
| `model` | string | yes* | — | Model identifier sent to the API (*not required for `mock` provider) |
| `base_url` | string | no | — | Override the API base URL (e.g. for Ollama: `http://localhost:11434/v1`) |
| `api_key` | string | no | — | API key. Supports `${ENV_VAR}` substitution. Defaults to `OPENAI_API_KEY` env var. |
| `temperature` | float | no | — | Sampling temperature |
| `top_p` | float | no | — | Nucleus sampling top-p |
| `max_tokens` | integer | no | — | Maximum completion tokens |
| `seed` | integer | no | — | Random seed for reproducibility |
| `timeout` | integer | no | `120` | HTTP timeout in seconds |
| `json_mode` | boolean | no | auto | Force JSON response format. Auto-detected if not set. |
| `max_retries` | integer | no | `2` | HTTP-level retry count for 429/5xx errors |
| `retry_delay` | float | no | `1.0` | Base delay (seconds) for exponential backoff |
| `extra_params` | map | no | — | Extra key/value pairs forwarded verbatim to the API |
| `mock_responses` | list[string] | no | — | Response sequence for `mock` provider. Clamps to last entry. |
| `cache` | map | no | — | See [Cache config](#cache-config) |

**Example:**
```yaml
models:
  gpt4:
    provider: openai_compat
    model: gpt-4o
    temperature: 0.2
    api_key: ${OPENAI_API_KEY}
  local:
    provider: openai_compat
    model: llama3.2
    base_url: http://localhost:11434/v1
    api_key: ollama
```

---

## Cache config

Defined under `models.<name>.cache`:

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `enabled` | boolean | yes | — | Enable file-based response cache |
| `dir` | string | no | `.pyconveyor-cache` | Directory to store cache files |
| `ttl_days` | integer | no | — | Evict entries older than this many days |

**Example:**
```yaml
models:
  default:
    provider: openai_compat
    model: gpt-4o
    cache:
      enabled: true
      dir: .cache
      ttl_days: 7
```

---

## Step (common fields)

All step types share these fields:

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `name` | string | yes | — | Unique identifier for this step. Referenced in expressions as `steps.<name>`. |
| `type` | string | no | `llm` | One of `llm`, `ensemble`, `transform`, `io`, `validate`, `parallel`, `condition` |
| `condition` | expression | no | — | Skip this step if expression evaluates falsy |
| `on_error` | string | no | `raise` | One of `raise`, `continue`, `skip_remaining` |
| `on_failure` | string | no | — | Dotted import path `module:fn` called on error: `fn(step_name, exc, rctx)` |
| `optional` | boolean | no | `false` | For child steps inside `parallel`: failure doesn't abort the group |
| `save` | `false` or string | no | *(auto)* | Output saving override when `outputs:` is present. `false` suppresses the file; a string sets a custom filename. `true` is rejected at load time. |

---

## LLM step (`type: llm`)

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `model` | string | yes | — | Must match a key under `models:` |
| `prompt` | string | yes | — | Jinja2 template filename (resolved relative to the pipeline file) |
| `system` | string | no | — | System message. Inline string or `{{ expression }}`. |
| `schema` | string | no | — | Dotted import path `module:ClassName` for a Pydantic model |
| `parser` | string | no | — | Named parser key from top-level `parsers:`, or `module:fn` |
| `vars` | map | no | — | Extra template variables. Values may be `{{ expressions }}`. |
| `max_attempts` | integer | no | `3` if schema set else `1` | Retry budget |
| `error_feedback` | boolean | no | `true` if schema set | Inject validation errors into retry context |
| `retry_on` | list[string] | no | `[parse, schema]` | Which error types trigger a retry |
| `retry_hint` | string | no | `""` | Custom hint appended to every error feedback message |
| `schema_strict` | boolean | no | `true` | Fail if the response has extra fields (Pydantic strict mode) |
| `error_template` | string | no | — | Custom Jinja2 template for error feedback messages |
| `max_feedback_tokens` | integer | no | `4000` | Max characters of previous output echoed in feedback |

**Example:**
```yaml
steps:
  - name: extract
    type: llm
    model: gpt4
    prompt: extract.j2
    schema: schemas:Metadata
    max_attempts: 3
    vars:
      focus: "{{ ctx.focus_area }}"
```

---

## Ensemble step (`type: ensemble`)

Runs N LLM members in parallel. If a judge is configured and its condition is met, the judge merges all outputs into a single result. Falls back to the first succeeded member if the judge is skipped or fails.

### Ensemble-level fields

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `members` | list | yes | — | At least one member definition (see below) |
| `prompt` | string | no | — | Jinja2 template shared by all members (each member can override) |
| `schema` | string | no | — | `module:ClassName` Pydantic model shared by all members and the judge |
| `judge` | map | no | — | Judge configuration (see below) |

### Member fields (each item under `members:`)

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `model` | string | yes | — | Must match a key under `models:` |
| `name` | string | no | model key | Display name; also the key for `steps.{ensemble}.{name}` |
| `required` | boolean | no | `true` | If `false`, member failure is non-fatal |
| `prompt` | string | no | — | Overrides the ensemble-level prompt for this member |
| `temperature` | float | no | — | Per-member sampling temperature |
| `top_p` | float | no | — | Per-member nucleus sampling |
| `max_tokens` | integer | no | — | Per-member token limit |
| `seed` | integer | no | — | Per-member random seed |
| `max_attempts` | integer | no | — | Per-member retry budget |
| `error_feedback` | boolean | no | — | Per-member error feedback toggle |
| `retry_hint` | string | no | — | Per-member retry hint |
| `schema_strict` | boolean | no | — | Per-member strict schema validation |
| `retry_on` | list[string] | no | — | Per-member retry triggers |
| `max_feedback_tokens` | integer | no | — | Per-member feedback token cap |
| `vars` | map | no | — | Per-member extra template variables |
| `system` | string | no | — | Per-member system message |

### Judge fields (under `judge:`)

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `model` | string | yes | — | Must match a key under `models:` |
| `condition` | string | no | `all_succeeded` | `all_succeeded` or `any_succeeded` |
| `prompt` | string | no | — | Jinja2 template for the judge. If omitted, the member prompt is auto-extended with a built-in merge instruction |
| `temperature` | float | no | — | Judge sampling temperature |
| `max_attempts` | integer | no | — | Judge retry budget |
| `system` | string | no | — | Judge system message |
| `schema_strict` | boolean | no | — | Judge strict schema validation |

**Condition values:**
- `all_succeeded` — judge only runs when every required member succeeds
- `any_succeeded` — judge runs as long as at least two members succeeded

**Example:**
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

Access individual member results downstream:
```yaml
  - name: verify
    type: transform
    fn: steps:verify
    inputs:
      primary:  "{{ steps.extract.gpt4o }}"
      reviewer: "{{ steps.extract.claude }}"
```

---

## Transform step (`type: transform`)

Runs a Python callable with the resolved inputs as keyword arguments.

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `fn` | string | yes | — | `module:callable` import path |
| `inputs` | map | no | — | Keyword arguments. Values may be `{{ expressions }}`. |

**Example:**
```yaml
steps:
  - name: clean
    type: transform
    fn: steps:clean_text
    inputs:
      text: "{{ ctx.raw_text }}"
```

---

## IO step (`type: io`)

Like `transform` but semantically intended for I/O operations (file reads, HTTP, etc.).
Uses the same `fn` + `inputs` fields.

---

## Validate step (`type: validate`)

Like `transform` but the callable must return a truthy value; a falsy return raises
`SchemaValidationError`.  Uses the same `fn` + `inputs` fields.

---

## Parallel step (`type: parallel`)

Runs child steps concurrently using a thread pool.

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `steps` | list | yes | — | Child step definitions (any step type) |

The result of a `parallel` step is a `dict` keyed by child step name.

**Example:**
```yaml
steps:
  - name: multi_extract
    type: parallel
    steps:
      - name: primary
        type: llm
        model: gpt4
        prompt: extract.j2
        schema: schemas:Metadata
      - name: reviewer
        type: llm
        model: gpt4
        prompt: review.j2
        schema: schemas:Review
```

---

## Condition step (`type: condition`)

Branches execution based on an expression.

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `if` | expression | yes | — | Boolean expression. Uses `ctx.*` and `steps.*`. |
| `then` | list | yes | — | Steps to run when `if` is truthy |
| `else` | list | no | — | Steps to run when `if` is falsy |

**Example:**
```yaml
steps:
  - name: check_language
    type: condition
    if: "steps.detect.language == 'en'"
    then:
      - name: en_extract
        type: llm
        model: gpt4
        prompt: en_extract.j2
        schema: schemas:English
    else:
      - name: translate_first
        type: transform
        fn: steps:translate
        inputs:
          text: "{{ ctx.document }}"
```

---

## Expressions

Expressions appear in `{{ }}` delimiters inside YAML string values, in `condition:` fields,
and in `if:` fields of condition steps.

### Namespace

| Name | Type | Description |
|------|------|-------------|
| `ctx` | proxy | Wraps the input dict. `ctx.missing_key` returns `None` rather than erroring. |
| `steps` | proxy | Wraps completed step results. `steps.name.field` delegates to the result value. |

### Allowed operations

- Attribute access: `ctx.field`, `steps.extract.primary`
- Item lookup: `ctx["key"]`
- Comparisons: `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`
- Identity checks (normalised): `is not none` → `!= None`, `is none` → `== None`
- Boolean operators: `and`, `or`, `not`
- Ternary: `value if condition else fallback`
- Literals: strings, numbers, booleans, `None`, lists and tuples of literals
- Allowed helpers: `first_non_none(a, b, ...)`, `active_models(ctx.models)`, `len(collection)`

### Security

Any expression containing disallowed AST nodes (lambdas, comprehensions, imports, etc.)
raises `ExpressionSecurityError` at pipeline **load time**, before any run begins.

### Examples

```yaml
# Conditional step gate
condition: "ctx.language is not none"

# Inline substitution
vars:
  greeting: "Hello {{ ctx.name }}!"

# Ternary
vars:
  mode: "{{ 'strict' if ctx.strict else 'lenient' }}"

# Reference a previous step's output
inputs:
  text: "{{ steps.clean.value }}"
```

---

## Environment variable expansion

Any YAML string value may contain `${VAR_NAME}` references which are expanded from
the process environment (and `.env` files loaded via `python-dotenv`).

```yaml
models:
  default:
    api_key: ${OPENAI_API_KEY}
    base_url: ${LLM_BASE_URL}
```

---

## Outputs

Defined under `outputs:`. When present, pyconveyor writes step results to disk after each run. Writes are skipped when the pipeline fails or is running in dry-run mode. All filesystem errors are non-fatal (logged as warnings).

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `dir` | string | no | `./outputs` | Output directory. May be a Jinja2 expression evaluated against `ctx`. |
| `final_as` | string | no | — | Filename to write the last non-`None` step result (e.g. `result.json`). Detected at load time if it collides with an auto-generated step filename. |

**Per-step `save:` key** (added to any step definition):

| Value | Meaning |
|-------|---------|
| *(absent)* | Auto-save: write `{step_name}.json` |
| `false` | Suppress: do not write a file for this step |
| `"custom.json"` | Write the result to the given filename inside `outputs.dir` |

`save: true` is rejected at load time with a `StepConfigError`.

Ensemble steps with no explicit `save:` additionally write each member's result as `{step}.{member}.json`.

Path traversal protection: any filename that resolves outside `outputs.dir` is silently skipped.

**Example:**
```yaml
outputs:
  dir: "./results/{{ ctx.run_id }}"
  final_as: result.json

steps:
  - name: classify
    type: llm
    model: default
    prompt: prompts/classify.j2
    schema:
      label: str
      confidence: float
    # Default: saves as classify.json

  - name: postprocess
    type: transform
    fn: steps:clean
    inputs:
      data: "{{ steps.classify }}"
    save: false   # suppress — this is an intermediate step
```

---

## Vocabulary

Defined under `vocabularies.<name>`:

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `known` | list[string] | yes | — | Canonical terms |
| `label` | string | no | `"vocabulary"` | Human-readable label used in summaries |
| `fuzzy_match` | boolean | no | `true` | Enable substring + edit-distance matching |
| `case_sensitive` | boolean | no | `false` | Whether matching is case-sensitive |

**Example:**
```yaml
vocabularies:
  plastic_type:
    known: [PET, PE, PLA, ABS, PS]
    fuzzy_match: true
    case_sensitive: false
```

---

## Full example

```yaml
models:
  default:
    provider: openai_compat
    model: gpt-4o
    temperature: 0.1
    api_key: ${OPENAI_API_KEY}
    cache:
      enabled: true
      ttl_days: 7

vocabularies:
  material:
    known: [steel, aluminium, copper, plastic]

outputs:
  dir: ./outputs
  final_as: result.json

steps:
  - name: extract
    type: llm
    model: default
    prompt: extract.j2
    schema: schemas:Metadata
    max_attempts: 3

  - name: check
    type: condition
    if: "steps.extract is not none"
    then:
      - name: enrich
        type: transform
        fn: steps:enrich
        inputs:
          data: "{{ steps.extract }}"
        save: false   # intermediate step — suppress output file
    on_error: continue
```
