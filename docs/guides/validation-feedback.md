# Validation Feedback

pyconveyor's most important feature: when a model returns malformed output, it feeds the error back so the model can fix itself — without any code.

## The problem

Retrying blindly doesn't work. If you send the same prompt again after a schema validation failure, the model tends to make the same mistake. It has no idea what went wrong.

pyconveyor solves this by treating retries as a **conversation**. After each failed attempt, it appends the model's previous output and a description of the error to the message history. The model sees its own prior turn adjacent to the correction request — the same way a human reviewer would highlight a mistake.

## How it works

Two failure modes get unified treatment:

- **Parse error** — the response wasn't valid JSON (markdown fences with extra prose, a partial truncation, etc.)
- **Schema error** — the response parsed, but violated the Pydantic schema (missing required field, wrong type, value outside a constraint)

When `error_feedback: true` and a retryable error occurs, pyconveyor constructs a multi-turn conversation:

```python
[
    {"role": "system",    "content": "<original system prompt>"},
    {"role": "user",      "content": "<original rendered prompt>"},
    {"role": "assistant", "content": "<previous raw response>"},
    {"role": "user",      "content": "<feedback block>"},
]
```

This structure is identical for parse and schema errors. Only the feedback block content differs.

### Schema error feedback

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

### Parse error feedback

```
Your previous response was not valid JSON:

```
Here is the extracted data:
{ "entries": [...]
```

Please return only a valid JSON object, with no surrounding prose or markdown fences.
```

## Configuration

```yaml
steps:
  - name: extract
    type: llm
    model: primary
    prompt: prompts/extract.j2
    schema: schemas:ExtractionResult

    max_attempts: 3           # 1 initial + up to 2 feedback retries
    error_feedback: true      # default when schema: is set
    retry_hint: "Return only a JSON object. No markdown fences."
```

### Smart defaults

Setting `schema:` on an `llm` step changes the defaults automatically:

| Setting | Without `schema:` | With `schema:` |
|---|---|---|
| `max_attempts` | `1` | `3` |
| `error_feedback` | `false` | `true` |

This means validation feedback fires by default for any step that has a schema. Set `max_attempts: 1` explicitly to opt out.

## Full configuration reference

| Field | Default | Description |
|---|---|---|
| `max_attempts` | `3` (with schema), `1` (without) | Total attempt budget |
| `error_feedback` | `true` (with schema) | Append previous output + error on retry |
| `retry_hint` | `""` | Static text appended to every retry feedback message |
| `retry_on` | `["parse", "schema"]` | Which error categories trigger a retry |
| `schema_strict` | `true` | Treat validation errors as failures |
| `max_feedback_tokens` | `4000` | Cap on previous output echoed back |
| `error_template` | built-in | Custom Jinja2 template for feedback messages |

### `retry_on` — granular control

```yaml
- name: extract
  type: llm
  schema: schemas:ExtractionResult
  max_attempts: 3
  retry_on: [schema, parse]     # default: retry on bad output, not on timeouts
```

Available categories:

| Category | Triggers on |
|---|---|
| `schema` | Pydantic `ValidationError` |
| `parse` | Response wasn't valid JSON |
| `timeout` | Request exceeded `timeout` seconds |
| `http_error` | Provider returned 5xx |
| `rate_limit` | Provider returned 429 |

### `max_feedback_tokens`

Each retry echoes the previous output back into the message history. For long extractions, attempt 3 can be 3× the original prompt length. `max_feedback_tokens` caps how much previous output is included; anything beyond it is truncated with a `[…truncated for length…]` marker.

```yaml
- name: extract
  type: llm
  schema: schemas:ExtractionResult
  max_attempts: 3
  max_feedback_tokens: 4000   # default
```

### Custom error template

Override the default feedback messages with a Jinja2 template:

```yaml
- name: extract
  type: llm
  schema: schemas:ExtractionResult
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
| `previous_output` | `str` | always |
| `errors` | `list` with `loc_str`, `msg`, `type` | `error_type == "schema"` |
| `parse_error_message` | `str` | `error_type == "parse"` |
| `attempt` | `int` | always (1-indexed) |
| `retry_hint` | `str` | always (may be empty) |

## Attempt sequence example

For `max_attempts: 3` with default `error_feedback: true`:

```
Attempt 1:  [system, user(prompt)]
            → ValidationError: entries[0].confidence field required

Attempt 2:  [system, user(prompt), assistant(output_1), user(feedback_1)]
            → ValidationError: entries[0].evidence must have ≥ 1 item

Attempt 3:  [system, user(prompt), assistant(output_2), user(feedback_2)]
            → Success: valid ExtractionResult returned
```

## Inspecting attempts

Every attempt is recorded in `rctx.metadata["attempt_logs"]`:

```python
result = runner.run(input_data)

# Quick access to the final attempt
step = result.steps["extract"]
print(step.last_attempt.attempt_number)     # 3
print(step.last_attempt.elapsed_seconds)    # 1.9
print(step.last_attempt.error_type)         # None (success)

# Full history
for attempt in step.attempts:
    print(attempt.attempt_number, attempt.status, attempt.errors)
```

For failed pipelines, failure introspection:

```python
if result.failed:
    failed_step = result.failure_state.step_name
    last = result.steps[failed_step].last_attempt

    print(last.raw_output)      # what the model returned on the final attempt
    print(last.errors)          # list of validation errors
    print(last.error_type)      # "schema_error" | "parse_error" | ...
```

## `schema_strict: false` — partial output mode

By default, any Pydantic validation error is a failure. For cases where losing some records to a bad field shouldn't kill the rest of the extraction:

```yaml
- name: extract
  type: llm
  schema: schemas:ExtractionResult
  schema_strict: false
```

In non-strict mode:
- Pydantic errors are recorded in `last_attempt.errors` but don't trigger a retry
- The step's result is the **parsed dict**, not a validated model instance
- Parse errors still retry per `retry_on`

This is intentionally opt-in. The strict default is correct for most pipelines.
