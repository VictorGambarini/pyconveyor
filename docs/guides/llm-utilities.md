# LLM Utilities

pyconveyor's LLM utilities are importable independently for scripts that don't need the full pipeline runner.

```python
from pyconveyor.llm import make_client, call_llm, probe_json_mode, extract_json
from pyconveyor.prompt import render_prompt, render_prompt_string
```

---

## `make_client`

Creates an OpenAI-compatible client.

```python
from pyconveyor.llm import make_client

client = make_client(
    base_url="https://api.openai.com/v1",
    api_key="sk-...",
)
```

Also accepts `timeout` and any keyword arguments that `openai.OpenAI` supports.

---

## `probe_json_mode`

Tests whether a model supports JSON mode (`response_format={"type": "json_object"}`).

```python
from pyconveyor.llm import make_client, probe_json_mode

client = make_client(base_url="...", api_key="...")
supported = probe_json_mode(client, "gpt-4o-mini", timeout=30)
# True or False
```

Sends a minimal test request. Falls back gracefully — returns `False` if the endpoint doesn't support it, rather than raising.

---

## `call_llm`

Calls the model with a messages array and returns the raw response string.

```python
from pyconveyor.llm import make_client, call_llm

client = make_client(base_url="...", api_key="...")

response = call_llm(
    client,
    messages=[{"role": "user", "content": "Extract the key points from: ..."}],
    model="gpt-4o-mini",
    timeout=120,
    json_mode=True,         # use response_format={"type": "json_object"}
    temperature=0.0,
    max_tokens=2048,
)
# response is a str — the model's raw output
```

### Parameters

| Parameter | Description |
|---|---|
| `client` | An `openai.OpenAI` client (from `make_client`) |
| `messages` | List of `{"role": ..., "content": ...}` dicts |
| `model` | Model name string |
| `timeout` | Request timeout in seconds |
| `json_mode` | Whether to use `response_format={"type": "json_object"}` |
| `temperature` | Sampling temperature (optional) |
| `top_p` | Top-p sampling (optional) |
| `max_tokens` | Max response tokens (optional) |
| `seed` | Random seed for reproducibility (optional) |
| `extra_params` | Dict of additional parameters passed through to the API |

---

## `extract_json`

Extracts a JSON object from a string that may contain surrounding prose, markdown fences, or other noise.

```python
from pyconveyor.llm import extract_json

raw = '''
Here is the extracted data:
```json
{"title": "Example", "key_points": ["Point one"]}
```
'''

data = extract_json(raw)
# {"title": "Example", "key_points": ["Point one"]}
```

Handles common model output patterns:

- Fenced code blocks (` ```json ... ``` ` or ` ``` ... ``` `)
- Prose before/after the JSON object
- BOM characters
- Trailing commas (best-effort)

Raises `ValueError` if no valid JSON object can be found.

`extract_json` is the default parser for `llm` steps. You only need to call it directly if you're using the utilities standalone or writing a custom parser.

---

## `render_prompt`

Renders a Jinja2 template file with context variables.

```python
from pyconveyor.prompt import render_prompt

prompt = render_prompt(
    "prompts/",           # template directory
    "extract.j2",         # template filename
    document=text,        # keyword args become template variables
    mode="detailed",
)
```

The template receives all keyword arguments as top-level variables:

```jinja2
{# prompts/extract.j2 #}
Extract {{ mode }} information from:

{{ document }}
```

---

## `render_prompt_string`

Renders a Jinja2 template from a string rather than a file.

```python
from pyconveyor.prompt import render_prompt_string

template = "Extract information from: {{ document }}"
prompt = render_prompt_string(template, document=text)
```

---

## Using utilities standalone

A complete extraction script without the pipeline runner:

```python
from pyconveyor.llm import make_client, call_llm, probe_json_mode, extract_json
from pyconveyor.prompt import render_prompt
from schemas import ExtractionResult

client = make_client(
    base_url="https://api.openai.com/v1",
    api_key="sk-...",
)

json_mode = probe_json_mode(client, "gpt-4o-mini", timeout=30)

prompt = render_prompt("prompts/", "extract.j2", document=text)

raw = call_llm(
    client,
    messages=[{"role": "user", "content": prompt}],
    model="gpt-4o-mini",
    timeout=120,
    json_mode=json_mode,
    temperature=0.0,
)

data = extract_json(raw)
result = ExtractionResult(**data)
print(result.title)
```

This is exactly what the pipeline runner does internally for each `llm` step, minus the retry loop and schema feedback.
