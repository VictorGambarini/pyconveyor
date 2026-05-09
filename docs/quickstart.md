# Quickstart

Get a working extraction pipeline in under 5 minutes.

## Install

```bash
pip install pyconveyor
```

For Anthropic support:

```bash
pip install "pyconveyor[anthropic]"
```

## Bootstrap a project

```bash
pyconveyor init my_pipeline/
cd my_pipeline/
```

This creates:

```
my_pipeline/
├── pipeline.yaml          # pipeline spec
├── prompts/
│   └── extract.j2         # example prompt template
├── schemas.py             # example Pydantic schema
├── steps.py               # example step functions
├── pyconveyor-schema.json # JSONSchema for editor autocomplete
└── .vscode/
    └── settings.json      # editor autocomplete config
```

## Set your API key

```bash
export OPENAI_API_KEY=sk-...
# or for local models:
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama
```

## Run

```bash
pyconveyor run pipeline.yaml --input '{"document": "The quick brown fox."}'
```

Output:

```json
{
  "steps": {
    "extract": {
      "title": "The quick brown fox",
      "key_points": ["A fox described as quick and brown"]
    }
  },
  "summary": {
    "steps_run": ["extract"],
    "steps_skipped": [],
    "llm_calls": 1,
    "elapsed_seconds": 1.23
  }
}
```

## Understand the generated files

### `pipeline.yaml`

```yaml
models:
  default:
    provider: openai_compat
    base_url: ${OPENAI_BASE_URL}
    api_key:  ${OPENAI_API_KEY}
    model:    ${MODEL_NAME:-gpt-4o-mini}
    timeout:  120

steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema: schemas:ExtractionResult
    max_attempts: 3
```

`${VAR}` syntax reads from environment variables. `${VAR:-default}` provides a fallback.

### `schemas.py`

```python
from pydantic import BaseModel
from typing import List

class ExtractionResult(BaseModel):
    title: str
    key_points: List[str]
```

The `schema:` field in the pipeline points to this class as `schemas:ExtractionResult` (module:class). pyconveyor validates every LLM response against it and retries automatically if validation fails.

### `prompts/extract.j2`

```jinja2
Extract structured information from the following document.

Document:
{{ ctx.document }}

Return a JSON object with the following fields:
- "title": string — the document title or a short summary
- "key_points": array of strings — up to 5 key points
```

`ctx` is the input dict passed to `runner.run()`. All keys are available as `ctx.<key>`.

## Use from Python

```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("my_pipeline/pipeline.yaml")
result = runner.run({"document": "Full text of the paper…"})

if result.failed:
    print("Failed at step:", result.failure_state.step_name)
    print("Error:", result.failure_state.exception)
else:
    extraction = result.steps["extract"].value  # ExtractionResult instance
    print(extraction.title)
    print(extraction.key_points)
```

## Validate without running

```bash
pyconveyor validate pipeline.yaml
# ✓ pipeline.yaml is valid
```

Catches all errors — bad field names, missing imports, invalid expressions — before spending any tokens.

## Next steps

- [Concepts](concepts.md) — understand the data flow
- [Step Types](guides/step-types.md) — add transform, validate, and parallel steps
- [Validation Feedback](guides/validation-feedback.md) — how self-correcting retries work
- [YAML Schema](reference/schema.md) — full field reference
