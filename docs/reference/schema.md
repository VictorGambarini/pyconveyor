# YAML Schema Reference

Complete reference for every field in a pyconveyor pipeline YAML file.

## Top-level structure

```yaml
models:       # required if any step uses type: llm
  <name>: ...

parsers:      # optional
  <name>: "module:function"

steps:        # required
  - name: ...
    type: ...
```

---

## `models` block

Named model configurations. Each key is a name referenced by `model:` in steps.

```yaml
models:
  primary:
    provider: openai_compat
    base_url: ${OPENAI_BASE_URL}
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o-mini
    timeout:  120
```

### Model fields

| Field | Type | Default | Description |
|---|---|---|---|
| `provider` | string | `openai_compat` | `openai_compat` \| `anthropic` \| `mock` |
| `base_url` | string | — | API base URL. Supports `${ENV_VAR}` syntax |
| `api_key` | string | — | API key. Supports `${ENV_VAR}` syntax |
| `model` | string | — | Model name string |
| `timeout` | integer | `120` | Request timeout in seconds |
| `required` | boolean | `true` | If `false`, pipeline continues without this model when env vars are absent |
| `temperature` | number | provider default | Sampling temperature |
| `top_p` | number | unset | Top-p sampling |
| `max_tokens` | integer | unset | Max response tokens |
| `seed` | integer | unset | Random seed for reproducible outputs |
| `max_retries` | integer | `2` | HTTP-level retries on 429/5xx |
| `retry_delay` | number | `1.0` | Seconds between HTTP retries |
| `extra_params` | object | — | Passed through to the API verbatim |
| `pricing.input_per_1k` | number | — | USD per 1k input tokens (for cost tracking) |
| `pricing.output_per_1k` | number | — | USD per 1k output tokens (for cost tracking) |
| `cache.enabled` | boolean | `false` | Enable development response cache |
| `cache.dir` | string | `.pyconveyor-cache` | Cache directory |
| `cache.ttl_days` | number | unset | Cache TTL in days |

### Environment variable substitution

`${VAR}` is replaced with the value of environment variable `VAR`. `${VAR:-default}` provides a fallback if `VAR` is unset.

```yaml
model: ${MODEL_NAME:-gpt-4o-mini}
```

---

## `parsers` block

Named parser functions referenced by `parser:` in `llm` steps.

```yaml
parsers:
  extraction: myproject.parsers:parse_extraction
```

The value is `module:function` — a dotted module path and function name separated by `:`.

---

## `steps` array

An ordered list of steps. Steps execute top-to-bottom. Each step has a `name` (unique within the pipeline) and a `type`.

### Common fields (all step types)

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Unique step identifier. Used in expressions as `steps.<name>` |
| `type` | string | `llm` | `llm` \| `ensemble` \| `transform` \| `validate` \| `io` \| `parallel` \| `condition` |
| `required` | boolean | `true` | If `false`, step failure is tolerated |
| `on_error` | string | `raise` | `raise` \| `continue` \| `skip_remaining` |
| `on_failure` | string | — | `module:function` called with `(step_name, exception, rctx)` on failure |
| `condition` | string | — | Expression; step is skipped if falsy (not applicable to `condition` type) |

---

### `llm` step fields

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | string | required | Name from the `models:` block |
| `prompt` | string | required | Path to a Jinja2 template, relative to the pipeline file |
| `system` | string | — | System prompt string (not a template path) |
| `schema` | string | — | `module:ClassName` — a Pydantic `BaseModel` subclass |
| `parser` | string | — | `module:function` or a key from `parsers:` block |
| `vars` | object | — | Extra variables injected into the prompt template |
| `max_attempts` | integer | `3` (with schema), `1` (without) | Total attempt budget |
| `error_feedback` | boolean | `true` (with schema) | Feed previous output + error back on retry |
| `retry_hint` | string | `""` | Static text appended to every retry feedback message |
| `retry_on` | array | `["parse", "schema"]` | Error categories that trigger a retry |
| `schema_strict` | boolean | `true` | Treat validation errors as failures |
| `max_feedback_tokens` | integer | `4000` | Cap on previous output echoed back in feedback |
| `error_template` | string | built-in | Path to a Jinja2 template for custom feedback messages |
| `temperature` | number | model default | Step-level override |
| `top_p` | number | model default | Step-level override |
| `max_tokens` | integer | model default | Step-level override |
| `seed` | integer | model default | Step-level override |
| `max_prompt_tokens` | integer | unset | Raises `PromptTooLargeError` if the outgoing message exceeds this |

#### `retry_on` values

| Value | Triggers on |
|---|---|
| `schema` | Pydantic `ValidationError` |
| `parse` | Response wasn't valid JSON |
| `timeout` | Request exceeded `timeout` |
| `http_error` | Provider 5xx |
| `rate_limit` | Provider 429 |

---

### `ensemble` step fields

| Field | Type | Default | Description |
|---|---|---|---|
| `members` | array | required | At least one member definition |
| `prompt` | string | — | Shared Jinja2 template path; inherited by all members unless overridden |
| `schema` | string | — | `module:ClassName` Pydantic model shared by all members and the judge |
| `judge` | object | — | Judge configuration (see below) |

**Member fields** (each item in `members:`):

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | string | required | Name from the `models:` block |
| `name` | string | model key | Member name; accessible as `steps.{ensemble}.{name}` |
| `required` | boolean | `true` | If `false`, member failure does not abort the ensemble |
| `prompt` | string | — | Overrides the ensemble-level prompt for this member |
| `temperature` | number | model default | Per-member override |
| `max_attempts` | integer | model default | Per-member retry budget |
| `vars` | object | — | Per-member extra template variables |
| `system` | string | — | Per-member system message |
| `seed`, `top_p`, `max_tokens`, `max_feedback_tokens`, `retry_hint`, `schema_strict`, `retry_on`, `error_feedback` | various | — | Same as `llm` step |

**Judge fields** (under `judge:`):

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | string | required | Name from the `models:` block |
| `condition` | string | `all_succeeded` | `all_succeeded` — run only when all required members succeeded; `any_succeeded` — run when two or more members succeeded |
| `prompt` | string | auto | Jinja2 template for the judge. If omitted, the shared member prompt is auto-extended with a built-in merge instruction |
| `temperature`, `max_attempts`, `system`, `schema_strict`, `max_feedback_tokens`, `retry_on`, `error_feedback` | various | — | Same as `llm` step |

---

### `transform` / `io` step fields

| Field | Type | Default | Description |
|---|---|---|---|
| `fn` | string | required | `module:function` — the callable to invoke |
| `inputs` | object | — | Keyword arguments passed to `fn`. Values can be expressions |

---

### `validate` step fields

| Field | Type | Default | Description |
|---|---|---|---|
| `condition` | string | required | Expression; pipeline aborts if falsy |

---

### `parallel` step fields

| Field | Type | Default | Description |
|---|---|---|---|
| `steps` | array | required | Child steps to run concurrently |

Child steps can be any step type. Each child's name is accessible as `steps.<parallel_name>.<child_name>`.

---

### `condition` step fields

| Field | Type | Default | Description |
|---|---|---|---|
| `if` | string | required | Expression to evaluate |
| `then` | array | — | Steps to run if `if` is truthy |
| `else` | array | — | Steps to run if `if` is falsy |

---

## `on_error` behaviour matrix

| Value | After a step failure |
|---|---|
| `raise` | Pipeline stops; `result.failed = True`; `failure_state` populated |
| `continue` | Step result is `None`; downstream steps run; `result.failed = False` |
| `skip_remaining` | All later steps skipped with status `skipped`; `result.failed = False` |

---

## Defaults summary

### Model block

| Field | Default |
|---|---|
| `provider` | `openai_compat` |
| `timeout` | `120` |
| `required` | `true` |
| `max_retries` | `2` |
| `retry_delay` | `1.0` |
| `cache.enabled` | `false` |
| `cache.dir` | `.pyconveyor-cache` |

### LLM step

| Field | Default |
|---|---|
| `max_attempts` | `3` if `schema:` set, else `1` |
| `error_feedback` | `true` if `schema:` set, else `false` |
| `retry_hint` | `""` |
| `retry_on` | `["parse", "schema"]` |
| `schema_strict` | `true` |
| `max_feedback_tokens` | `4000` |
| `on_error` | `raise` |
| `required` | `true` |
