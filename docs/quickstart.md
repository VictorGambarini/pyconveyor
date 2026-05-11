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

---

## Option A — Interactive setup (recommended for new users)

The interactive setup guides you through defining your schema and choosing a provider. No Python files needed.

```bash
pyconveyor init my_pipeline/ --interactive
cd my_pipeline/
```

> **Screenshot placeholder:** terminal showing the interactive `pyconveyor init --interactive` prompts — asking for subject, field definitions, and provider choice.

You'll be asked:

1. **What are you extracting from?** (e.g. `invoices`, `articles`) — used as a label
2. **Output fields** — one per line, in `name:type` format:
   ```
   > invoice_number:str
   > vendor:str
   > amount:float
   > due_date:str | None
   >              ← press Enter to finish
   ```
3. **Which LLM provider?** — OpenAI, Anthropic, or Ollama

This generates a `pipeline.yaml` with an inline schema:

```yaml
models:
  default:
    provider: openai_compat
    api_key:  ${OPENAI_API_KEY}
    model:    ${MODEL_NAME:-gpt-4o-mini}
    timeout:  120

steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      invoice_number: str
      vendor: str
      amount: float
      due_date: str | None
    max_attempts: 3
```

No `schemas.py` file. The schema lives in the YAML.

You can add descriptions to any field — they are injected into the LLM prompt automatically via `{{ schema_hint }}`:

```yaml
    schema:
      invoice_number:
        type: str
        description: "Invoice identifier exactly as printed (e.g. INV-2024-001)."
      vendor:
        type: str
        description: "Vendor company name."
        min_length: 1
      amount:
        type: float
        description: "Total invoice amount, numeric only (no currency symbol)."
      due_date:
        type: str | None
        description: "Due date in YYYY-MM-DD format. Null if not stated."
```

See the **[YAML Schema guide](guides/yaml-schema.md)** for field constraints, nested objects, and `on_fail` behaviour.

---

## Option B — Static setup

If you prefer the traditional layout with a `schemas.py` file:

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

---

## Set your API key

```bash
export OPENAI_API_KEY=sk-...

# For local models (Ollama):
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama

# For Anthropic:
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Run

```bash
pyconveyor run pipeline.yaml --input '{"document": "Invoice from Acme Corp, $4,250 due 2024-03-15"}'
```

Output:

```json
{
  "steps": {
    "extract": {
      "invoice_number": null,
      "vendor": "Acme Corp",
      "amount": 4250.0,
      "due_date": "2024-03-15"
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

---

## Validate without running

```bash
pyconveyor validate pipeline.yaml
# ✓ pipeline.yaml is valid
```

Catches all errors — bad field names, missing imports, invalid expressions — before spending any tokens.

---

## Visualise the pipeline

```bash
pyconveyor visualise pipeline.yaml
```

```mermaid
graph TD
    extract
```

For multi-step pipelines this shows the full step DAG. Paste it into GitHub, GitLab, or Notion for a rendered diagram.

---

## Process a file with Python

```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("my_pipeline/pipeline.yaml")
result = runner.run({"document": "Full text of the document…"})

if result.failed:
    print("Failed at step:", result.failure_state.step_name)
    print("Error:", result.failure_state.exception)
else:
    extraction = result.steps["extract"].value
    print(extraction)  # dict (or Pydantic model if schemas.py is used)
```

---

## Process many documents at once

```bash
# input.jsonl — one document per line
echo '{"id": "1", "document": "Invoice from Acme…"}' >> input.jsonl
echo '{"id": "2", "document": "Receipt from Beta…"}' >> input.jsonl

pyconveyor batch pipeline.yaml --input input.jsonl --output results.jsonl --workers 8
```

---

## Measure accuracy with benchmarking

Once you have some documents with known-correct outputs, benchmark your pipeline:

```bash
# Create a benchmark case
mkdir -p benchmarks/case_001
echo '{"document": "Invoice from Acme Corp, $4,250"}' > benchmarks/case_001/input.json
echo '{"extract": {"vendor": "Acme Corp", "amount": 4250.0}}' > benchmarks/case_001/expected.json

# Run the benchmark
pyconveyor benchmark benchmarks/ --pipeline pipeline.yaml --report report.html
open report.html
```

See the [Benchmarking guide](guides/benchmarking.md) for details.

---

## Next steps

- [Concepts](concepts.md) — understand how pipelines, steps, and context fit together
- [Step Types](guides/step-types.md) — add `transform`, `validate`, `parallel`, and `condition` steps
- [Validation Feedback](guides/validation-feedback.md) — how self-correcting retries work
- [Benchmarking](guides/benchmarking.md) — measure and improve pipeline accuracy
- [YAML Schema](reference/schema.md) — full field reference
- [CLI Reference](reference/cli.md) — all commands and options
