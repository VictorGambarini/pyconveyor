# Providers

pyconveyor supports three built-in providers and allows registering custom ones.

## Built-in providers

| Provider string | Backend | Use case |
|---|---|---|
| `openai_compat` | `openai.OpenAI` | OpenAI, Ollama, vLLM, LM Studio, any OpenAI-compatible proxy |
| `anthropic` | `anthropic.Anthropic` | Native Anthropic API (requires `pip install "pyconveyor[anthropic]"`) |
| `mock` | Fixed string | Unit tests without API calls |

---

## `openai_compat`

The default provider. Works with any endpoint that implements the OpenAI API format.

```yaml
models:
  default:
    provider: openai_compat
    base_url: ${OPENAI_BASE_URL}
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o-mini
    timeout:  120
```

### OpenAI

```bash
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY=sk-...
```

### Ollama (local)

```bash
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama
export MODEL_NAME=llama3.2
```

### vLLM

```bash
export OPENAI_BASE_URL=http://localhost:8000/v1
export OPENAI_API_KEY=token-abc123
export MODEL_NAME=mistralai/Mistral-7B-Instruct-v0.3
```

### LM Studio

```bash
export OPENAI_BASE_URL=http://localhost:1234/v1
export OPENAI_API_KEY=lm-studio
```

---

## `anthropic`

Native Anthropic SDK. Install the optional dependency first:

```bash
pip install "pyconveyor[anthropic]"
```

```yaml
models:
  claude:
    provider: anthropic
    api_key:  ${ANTHROPIC_API_KEY}
    model:    claude-3-5-sonnet-20241022
    timeout:  120
    max_tokens: 4096
```

!!! note
    `base_url` is optional for Anthropic. Omit it to use the default `api.anthropic.com`.

---

## `mock`

Returns a fixed string for every call. Use in unit tests to avoid API calls.

```yaml
models:
  test_model:
    provider: mock
    model:    mock
    response: '{"title": "Test title", "key_points": ["Point one"]}'
```

The `response` field is returned verbatim as the model's output. pyconveyor then runs it through the normal parser and schema validation chain.

You can also configure a sequence of responses to simulate retry behaviour:

```python
# In tests — configure mock via model_overrides
runner = PipelineRunner("pipeline.yaml")
result = runner.run(
    input_data,
    model_overrides={
        "test_model": {
            "responses": [
                "not valid json",                          # attempt 1: parse error
                '{"title": null, "key_points": []}',      # attempt 2: schema error
                '{"title": "Good", "key_points": ["a"]}', # attempt 3: success
            ]
        }
    }
)
```

---

## Custom providers

Register a custom provider with a decorator:

```python
from pyconveyor import register_provider

@register_provider("my_backend")
def make_my_client(base_url: str, api_key: str, **kwargs):
    return MyClient(base_url=base_url, api_key=api_key)
```

The function receives the model block's fields as keyword arguments and must return a client object. Call it before creating any `PipelineRunner` instance.

Use it in YAML:

```yaml
models:
  custom:
    provider: my_backend
    base_url: ${MY_BACKEND_URL}
    api_key:  ${MY_BACKEND_KEY}
    model:    my-model-v1
```

---

## Model configuration

All providers share the same configuration fields:

```yaml
models:
  primary:
    provider: openai_compat
    base_url:    ${MODEL_BASE_URL}
    api_key:     ${MODEL_API_KEY}
    model:       ${MODEL_NAME}
    timeout:     120

    # Sampling parameters
    temperature: 0.1
    top_p:       0.95
    max_tokens:  4096
    seed:        42

    # HTTP retry behaviour (separate from schema retry loops)
    max_retries: 2       # retries on 429/5xx (default: 2)
    retry_delay: 1.0     # seconds between retries (default: 1.0)

    # Pass-through to the API
    extra_params:
      reasoning_effort: high
```

### Step-level overrides

Sampling parameters can be overridden at the step level:

```yaml
steps:
  - name: extract
    type: llm
    model: primary
    temperature: 0.0       # deterministic for this step
    prompt: prompts/extract.j2

  - name: paraphrase
    type: llm
    model: primary
    temperature: 0.7       # more creative for this step
    prompt: prompts/paraphrase.j2
```

### Programmatic overrides

Pass overrides at run time — useful for multi-tenant apps or testing:

```python
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

Overrides are merged on top of the YAML definition for that run only. The loaded pipeline spec is never mutated, so the same `runner` instance is safe to reuse with different overrides.

### `required: false`

Mark a model as optional. If the environment variables for that model are not set, the pipeline continues without it:

```yaml
models:
  reviewer:
    provider: openai_compat
    base_url: ${REVIEWER_BASE_URL}
    api_key:  ${REVIEWER_API_KEY}
    model:    ${REVIEWER_MODEL}
    required: false
```

Steps that reference an unconfigured `required: false` model produce `None` rather than failing.
