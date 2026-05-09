# pyconveyor

**Deterministic YAML pipeline engine for structured LLM extraction.**

[![PyPI](https://img.shields.io/pypi/v/pyconveyor)](https://pypi.org/project/pyconveyor/)
[![Python](https://img.shields.io/pypi/pyversions/pyconveyor)](https://pypi.org/project/pyconveyor/)
[![CI](https://github.com/VictorGambarini/pyconveyor/actions/workflows/ci.yml/badge.svg)](https://github.com/VictorGambarini/pyconveyor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

pyconveyor lets you build reliable LLM extraction pipelines by declaring them in YAML. It handles prompt rendering, schema validation, self-correcting retries, parallel steps, and controlled-vocabulary normalisation — so your code handles the domain logic, not the plumbing.

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema: schemas:ArticleSummary
    max_attempts: 3
```

```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("pipeline.yaml")
result = runner.run({"text": open("article.txt").read()})

summary = result.steps["extract"].value  # validated ArticleSummary instance
print(summary.title)
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

Bootstrap a working project in one command:

```bash
pyconveyor init my_project/
cd my_project/
export OPENAI_API_KEY=sk-...
pyconveyor run pipeline.yaml --input '{"document": "The quick brown fox."}'
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

When `runner.run(input_data)` is called:

1. The input dict becomes `ctx` — available in every prompt template and expression
2. Steps execute in declaration order
3. Each step's result is stored and can be referenced by later steps as `{{ steps.name.value }}`
4. A `RunContext` is returned with all results, attempt logs, and timing

---

## Features

### Structured output with automatic retries

Every `llm` step validates the model's response against a Pydantic schema. If validation fails, pyconveyor feeds the error back to the model and retries — up to `max_attempts` times.

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
| `llm` | Call a model, validate output against a Pydantic schema, retry on failure |
| `transform` | Call a Python function with step outputs as inputs |
| `validate` | Assert a condition; fail or skip remaining steps if it's false |
| `io` | Call a Python function for side effects (DB write, file save) |
| `parallel` | Run multiple sub-pipelines concurrently with `ThreadPoolExecutor` |
| `condition` | Branch to different steps based on a runtime expression |

### Provider support

| Provider | How |
|---|---|
| OpenAI | `provider: openai_compat` |
| Anthropic Claude | `provider: anthropic` + `pip install pyconveyor[anthropic]` |
| Ollama / vLLM / LM Studio | `provider: openai_compat` + `base_url:` override |
| Custom | `@register_provider("name")` decorator |
| Tests | `provider: mock` — no API calls |

### Vocabulary-constrained fields

`VocabField` constrains a Pydantic field to a controlled vocabulary, normalises fuzzy matches, and grows the vocabulary over time.

```python
from pyconveyor.vocab import Vocabulary, VocabField
from pydantic import BaseModel

PlasticVocab = Vocabulary(
    known={"PET", "PE", "PLA", "PP"},
    label="plastic_type",
    growth_policy="human",   # queue novel terms for CLI review
    persist=True,            # save after each run
)

class Record(BaseModel):
    plastic: str = VocabField(vocab=PlasticVocab)
    quantity: int
```

Growth policies: `"auto"` (add immediately), `"human"` (queue for CLI review), `"llm"` (LLM decides), or any callable `fn(VocabSuggestion) -> bool`.

Review pending terms interactively:

```bash
pyconveyor vocab review pipeline.yaml
```

### Batch processing

Process a JSONL file with configurable concurrency:

```bash
pyconveyor batch pipeline.yaml inputs.jsonl --concurrency 4 --output results.jsonl
```

```python
from pyconveyor import BatchRunner

runner = BatchRunner("pipeline.yaml", concurrency=4)
batch = runner.run_all(records)  # list of dicts
print(batch.summary())           # total, succeeded, failed, error_rate
```

### Load-time validation

`PipelineRunner("pipeline.yaml")` validates everything before spending any tokens — all schema imports, model references, expression syntax, and field names. Errors include the YAML line number and "did you mean?" suggestions.

```bash
pyconveyor validate pipeline.yaml
# ✓ pipeline.yaml is valid

# Or on error:
# pipeline.yaml:14: unknown field 'max_attempt' on llm step — did you mean 'max_attempts'?
```

### Hooks and observability

```python
runner.on_llm_call = lambda model, prompt, response: log_to_db(model, prompt, response)
runner.on_run_end  = lambda rctx: metrics.record(rctx.summary())
```

### Response caching

Cache LLM responses during development to avoid burning tokens on repeated runs:

```bash
pyconveyor run pipeline.yaml --input '...' --cache
pyconveyor run pipeline.yaml --input '...' --cache --cache-ttl 3600
```

### DAG visualisation

```bash
pyconveyor visualise pipeline.yaml
# Outputs Mermaid diagram
```

---

## CLI reference

```
pyconveyor init <dir>              Bootstrap a new project
pyconveyor run <pipeline.yaml>     Run a pipeline
pyconveyor validate <pipeline>     Validate without running
pyconveyor batch <pipeline> <jsonl> Batch process a JSONL file
pyconveyor vocab review <pipeline> Review pending vocabulary suggestions
pyconveyor schema                  Emit JSONSchema for editor autocomplete
pyconveyor visualise <pipeline>    Print Mermaid DAG diagram
```

---

## Python API

```python
from pyconveyor import PipelineRunner, BatchRunner

# Single run
runner = PipelineRunner("pipeline.yaml")
result = runner.run({"text": "..."})

result.failed                          # bool
result.steps["extract"].value          # Pydantic model instance
result.steps["extract"].last_attempt   # AttemptLog with timing and token counts
result.summary()                       # RunSummary with aggregates

# Batch
batch_runner = BatchRunner("pipeline.yaml", concurrency=8)
batch = batch_runner.run_all(records)
for record in batch.successes:
    save(record)
```

---

## Versioning policy

The YAML pipeline format (`pipeline.yaml`) is treated as a public API subject to the same semver rules as the Python API. A breaking change to the YAML schema will increment the major version.

---

## Documentation

Full documentation at **[pyconveyor.readthedocs.io](https://pyconveyor.readthedocs.io)**

- [Quickstart](https://pyconveyor.readthedocs.io/en/latest/quickstart/)
- [Step Types](https://pyconveyor.readthedocs.io/en/latest/guides/step-types/)
- [Vocabulary Fields](https://pyconveyor.readthedocs.io/en/latest/guides/vocab/)
- [Batch Processing](https://pyconveyor.readthedocs.io/en/latest/guides/batch/)
- [Response Caching](https://pyconveyor.readthedocs.io/en/latest/guides/caching/)
- [YAML Schema Reference](https://pyconveyor.readthedocs.io/en/latest/reference/schema/)

---

## License

MIT
