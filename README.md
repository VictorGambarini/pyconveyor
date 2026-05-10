# pyconveyor

**Deterministic YAML pipeline engine for structured LLM extraction.**

[![PyPI](https://img.shields.io/pypi/v/pyconveyor)](https://pypi.org/project/pyconveyor/)
[![Python](https://img.shields.io/pypi/pyversions/pyconveyor)](https://pypi.org/project/pyconveyor/)
[![CI](https://github.com/VictorGambarini/pyconveyor/actions/workflows/ci.yml/badge.svg)](https://github.com/VictorGambarini/pyconveyor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

pyconveyor lets you build reliable LLM extraction pipelines by declaring them in YAML. It handles prompt rendering, schema validation, self-correcting retries, parallel steps, batch processing, and benchmarking — so your code handles the domain logic, not the plumbing.

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      invoice_number: str
      vendor: str
      amount: float
    max_attempts: 3
```

```bash
pyconveyor run pipeline.yaml --input '{"document": "Invoice from Acme Corp…"}'
```

---

## Install

```bash
pip install pyconveyor
```

For Anthropic Claude support:

```bash
pip install "pyconveyor[anthropic]"
```

---

## Quickstart

Bootstrap a working project interactively — no Python files needed:

```bash
pyconveyor init my_project/ --interactive
cd my_project/
export OPENAI_API_KEY=sk-...
pyconveyor run pipeline.yaml --input '{"document": "The quick brown fox."}'
```

Or use the static layout with `schemas.py`:

```bash
pyconveyor init my_project/
```

---

## How it works

You write three files. pyconveyor owns the runner.

```
your_project/
├── pipeline.yaml       # what to do and in what order
├── schemas.py          # what shape the output must have (Pydantic models)
└── prompts/
    └── extract.j2      # what to ask the model (Jinja2 templates)
```

Or skip `schemas.py` and write the schema inline in YAML:

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      title: str
      key_points: list[str]
      confidence: float | None
```

When `runner.run(input_data)` is called:

1. The input dict becomes `ctx` — available in every prompt template and expression
2. Steps execute in declaration order
3. Each step's result is stored and can be referenced by later steps as `{{ steps.name.value }}`
4. A `RunContext` is returned with all results, attempt logs, and timing

---

## Features

### Structured output with automatic retries

Every `llm` step validates the model's response against a schema. If validation fails, pyconveyor feeds the error back to the model and retries automatically.

```yaml
- name: extract
  type: llm
  model: default
  prompt: prompts/extract.j2
  schema: schemas:ArticleSummary
  max_attempts: 3
  on_error: continue   # "raise" | "continue" | "skip_remaining"
```

### All step types

| Step type | What it does |
|---|---|
| `llm` | Call a model, validate output against a schema, retry on failure |
| `transform` | Call a Python function with step outputs as inputs |
| `validate` | Assert a condition; fail or skip remaining steps if it's false |
| `io` | Call a Python function for side effects (DB write, file save) |
| `parallel` | Run multiple sub-pipelines concurrently |
| `condition` | Branch to different steps based on a runtime expression |

### Inline schemas — no Python required

Define your output schema directly in the YAML file:

```yaml
schema:
  label: str
  confidence: float
  notes: str | None
```

Or generate a `schemas.py` stub from sample output:

```bash
pyconveyor run pipeline.yaml --input sample.json > output.json
pyconveyor schema infer pipeline.yaml --sample output.json --output schemas.py
```

### Benchmarking and reports

Measure pipeline accuracy against golden-standard cases and generate shareable HTML reports:

```bash
# Run benchmark, compare two pipelines, open report
pyconveyor benchmark benchmarks/ \
  --pipeline pipeline_v1.yaml \
  --pipeline pipeline_v2.yaml \
  --report comparison.html

open comparison.html
```

The report includes per-step accuracy tables, a pipeline comparison delta, a Mermaid graph with accuracy annotations, Chart.js bar charts, and a per-case collapsible breakdown.

```python
from pyconveyor import BenchmarkRunner, generate_report

runner = BenchmarkRunner(
    benchmark_dir="benchmarks/",
    pipelines=["pipeline_v1.yaml", "pipeline_v2.yaml"],
    pass_threshold=0.8,
)
summary = runner.run()
generate_report(summary, "report.html", pdf=True)
```

### Provider support

| Provider | How |
|---|---|
| OpenAI | `provider: openai_compat` |
| Anthropic Claude | `provider: anthropic` + `pip install pyconveyor[anthropic]` |
| Ollama / vLLM / LM Studio | `provider: openai_compat` + `base_url:` override |
| Custom | `@register_provider("name")` decorator |
| Tests | `provider: mock` — no API calls |

### Batch processing

Process thousands of documents with parallel workers:

```bash
pyconveyor batch pipeline.yaml --input documents.jsonl --output results.jsonl --workers 8
```

```python
from pyconveyor import BatchRunner

runner = BatchRunner("pipeline.yaml", max_workers=8)
for item_id, result in runner.run(records):
    if not result.failed:
        save(result.steps["extract"].value)
```

### Vocabulary-constrained fields

`VocabField` constrains a Pydantic field to a controlled vocabulary, normalises fuzzy matches, and grows the vocabulary over time.

```python
from pyconveyor.vocab import Vocabulary, VocabField
from pydantic import BaseModel

PlasticVocab = Vocabulary(
    known={"PET", "PE", "PLA", "PP"},
    label="plastic_type",
    growth_policy="human",   # queue novel terms for CLI review
    persist=True,
)

class Record(BaseModel):
    plastic: str = VocabField(vocab=PlasticVocab)
    quantity: int
```

Review pending terms interactively:

```bash
pyconveyor vocab review pipeline.yaml
```

### Load-time validation

`PipelineRunner("pipeline.yaml")` validates everything before spending any tokens:

```bash
pyconveyor validate pipeline.yaml
# ✓ pipeline.yaml is valid
```

Errors include the YAML line number and "did you mean?" suggestions.

### Response caching

Cache LLM responses during development to avoid burning tokens on repeated runs:

```bash
pyconveyor run pipeline.yaml --input input.json
# subsequent runs use cached responses by default
```

### DAG visualisation

```bash
pyconveyor visualise pipeline.yaml
# Outputs Mermaid diagram — paste into GitHub, GitLab, or Notion
```

---

## CLI reference

```
pyconveyor init <dir>                  Bootstrap a new project
pyconveyor init <dir> --interactive    Guided setup — define fields interactively
pyconveyor run <pipeline.yaml>         Run a pipeline
pyconveyor validate <pipeline>         Validate without running
pyconveyor batch <pipeline>            Batch process a JSONL file
pyconveyor benchmark <dir>             Benchmark against golden-standard cases
pyconveyor vocab review <pipeline>     Review pending vocabulary suggestions
pyconveyor schema                      Emit JSONSchema for editor autocomplete
pyconveyor schema infer <pipeline>     Infer schemas.py from sample output
pyconveyor visualise <pipeline>        Print Mermaid DAG diagram
```

---

## Python API

```python
from pyconveyor import PipelineRunner, BatchRunner, BenchmarkRunner, generate_report

# Single run
runner = PipelineRunner("pipeline.yaml")
result = runner.run({"text": "…"})

result.failed                          # bool
result.steps["extract"].value          # Pydantic model or dict
result.steps["extract"].last_attempt   # AttemptLog with timing and token counts
result.summary()                       # RunSummary with aggregates

# Batch
batch_runner = BatchRunner("pipeline.yaml", max_workers=8)
for item_id, result in batch_runner.run(records):
    save(result.steps["extract"].value)

# Benchmark
bench = BenchmarkRunner("benchmarks/", pipelines=["pipeline.yaml"])
summary = bench.run()
generate_report(summary, "report.html")
```

---

## Versioning policy

The YAML pipeline format (`pipeline.yaml`) is treated as a public API subject to the same semver rules as the Python API. A breaking change to the YAML schema will increment the major version.

---

## Documentation

Full documentation at **[pyconveyor.readthedocs.io](https://pyconveyor.readthedocs.io)**

- [Quickstart](https://pyconveyor.readthedocs.io/en/latest/quickstart/)
- [Step Types](https://pyconveyor.readthedocs.io/en/latest/guides/step-types/)
- [Benchmarking](https://pyconveyor.readthedocs.io/en/latest/guides/benchmarking/)
- [Vocabulary Fields](https://pyconveyor.readthedocs.io/en/latest/guides/vocab/)
- [Batch Processing](https://pyconveyor.readthedocs.io/en/latest/guides/batch/)
- [Response Caching](https://pyconveyor.readthedocs.io/en/latest/guides/caching/)
- [YAML Schema Reference](https://pyconveyor.readthedocs.io/en/latest/reference/schema/)
- [CLI Reference](https://pyconveyor.readthedocs.io/en/latest/reference/cli/)

---

## License

MIT
