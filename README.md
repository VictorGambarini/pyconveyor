# pyconveyor

**Deterministic YAML pipeline engine for structured LLM extraction.**

[![PyPI](https://img.shields.io/pypi/v/pyconveyor)](https://pypi.org/project/pyconveyor/)
[![Python](https://img.shields.io/pypi/pyversions/pyconveyor)](https://pypi.org/project/pyconveyor/)
[![CI](https://github.com/VictorGambarini/pyconveyor/actions/workflows/ci.yml/badge.svg)](https://github.com/VictorGambarini/pyconveyor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

pyconveyor lets you build reliable LLM extraction pipelines by declaring them in YAML. It handles prompt rendering, schema validation, self-correcting retries, parallel steps, batch processing, and benchmarking — so your code handles the domain logic, not the plumbing.

---

## Install

```bash
pip install pyconveyor
```

---

## A simple pipeline

Start with a single LLM step that extracts structured data from a scientific paper. Declare what you want in YAML — no Python required.

```yaml
# pipeline.yaml
models:
  default:
    provider: openai_compat
    api_key: ${OPENAI_API_KEY}
    model: gpt-4o-mini
    timeout: 120

steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      title: str
      authors: list[str]
      key_findings: list[str]
```

```jinja2
{# prompts/extract.j2 #}
Extract structured metadata from the following scientific paper.

Paper:
{{ ctx.paper }}

Return a JSON object with:
- "title": the paper title exactly as written
- "authors": list of author names
- "key_findings": up to 5 key findings as short sentences
```

```bash
pyconveyor run pipeline.yaml --input '{"paper": "Deep learning has revolutionized..."}'
```

That's it. pyconveyor calls the model, validates the output matches your schema, and retries automatically if the model returns something that doesn't fit.

---

## Bootstrapping a project

Use `pyconveyor init` to scaffold a working project in one command:

```bash
pyconveyor init my_project/ --interactive
cd my_project/
export OPENAI_API_KEY=sk-...
pyconveyor run pipeline.yaml --input '{"paper": "..."}'
```

The interactive mode asks what you're extracting, which fields you need, and which provider to use. It generates `pipeline.yaml`, prompt templates, and editor autocomplete config — ready to run.

```bash
pyconveyor init my_project/          # static layout with schemas.py
pyconveyor init my_project/ --interactive   # guided setup, inline schema
```

---

## Rich field descriptions

Add descriptions to your schema fields and they appear automatically in a `{{ schema_hint }}` variable you can place in any prompt. pyconveyor builds a plain-English field listing for you — no more copying field docs between schema and prompt.

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      title:
        type: str
        description: "Paper title exactly as written, including subtitle if present."
      authors:
        type: list[str]
        description: "All author names in order. Include affiliation superscripts if present."
      doi:
        type: str | None
        description: "DOI if listed. Null if not found."
        pattern: "^10\\.[0-9]{4,}/.+$"
      publication_year:
        type: int
        description: "Four-digit year of publication."
```

```jinja2
{# prompts/extract.j2 #}
Extract structured metadata from the following paper.

{{ schema_hint }}

Paper:
{{ ctx.paper }}
```

The `{{ schema_hint }}` renders as something like:

```
Return a JSON object with the following fields:

- **title** (str, required) — Paper title exactly as written, including subtitle if present.
- **authors** (list[str], required) — All author names in order. Include affiliation superscripts if present.
- **doi** (str | None) — DOI if listed. Null if not found.
- **publication_year** (int, required) — Four-digit year of publication.
```

You can also add `pattern`, `min_length`, `max_length`, `min_items`, and `max_items` constraints. Fields that fail constraints trigger a retry by default, or you can set `on_fail: null` to silently coerce invalid values to `None`, or `on_fail: warn` to log and continue.

---

## Multiple steps

Pipelines grow naturally. Each step's result is available to later steps as `{{ steps.name }}`.

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      title: str
      abstract: str
      methods: list[str]

  - name: classify
    type: llm
    model: default
    prompt: prompts/classify.j2
    schema:
      field: str
      subfield: str | None
      confidence: float
```

```jinja2
{# prompts/classify.j2 #}
Classify this paper into a research field based on its title and abstract.

Title: {{ steps.extract.title }}
Abstract: {{ steps.extract.abstract }}

Return:
- "field": the primary research field (e.g. "materials science", "molecular biology")
- "subfield": more specific subfield if identifiable
- "confidence": your confidence 0.0-1.0
```

Steps run in declaration order. A step can reference any prior step's output. The runner returns a `RunContext` with every step result, attempt logs, and timing.

---

## Controlled vocabularies

Constrain a field to a known set of terms. pyconveyor normalises fuzzy matches and captures novel values for review.

Define your vocabularies as YAML files in a `vocabularies/` directory:

```yaml
# vocabularies/organism.yaml
known:
  - Escherichia coli
  - Saccharomyces cerevisiae
  - Bacillus subtilis
  - Pseudomonas aeruginosa
  - Staphylococcus aureus
label: organism
growth_policy: auto    # auto-approve close matches
```

Reference them on schema fields by filename:

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      organism:
        type: str
        description: "Primary organism studied."
        vocab: organism        # loads vocabularies/organism.yaml
      strain:
        type: str | None
        description: "Strain designation if reported."
```

Or define a small vocabulary inline — useful for ad-hoc constraints:

```yaml
schema:
  study_type:
    type: str
    description: "Type of study conducted."
    vocab:
      terms:
        - in vitro
        - in vivo
        - in silico
        - clinical trial
        - field study
```

When the model returns "E. coli" instead of "Escherichia coli", pyconveyor normalises it automatically. When it returns a genuinely new organism, the value is captured as a suggestion. The `{{ vocab_hints }}` variable injects known terms into your prompt so the model knows the preferred vocabulary.

Review pending suggestions from the CLI:

```bash
pyconveyor vocab review
```

---

## Self-correcting retries

When a model returns output that doesn't match your schema, pyconveyor feeds the errors back to the model and lets it try again.

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      title: str
      authors: list[str]
      doi:
        type: str | None
        pattern: "^10\\.[0-9]{4,}/.+$"
    max_attempts: 3        # give the model up to 3 tries
```

If the model returns a malformed DOI on the first attempt, the second attempt receives:

```
Your previous response failed schema validation. Here is what you returned:

{"title": "A Study of...", "authors": [...], "doi": "doi:10.1234/abc"}

Validation errors:
- doi: String must match pattern ^10\.[0-9]{4,}/.+$

Please fix these issues and return a corrected JSON object.
```

This works for both schema validation errors and JSON parse errors. You control which error types trigger retries with `retry_on`, cap the feedback size with `max_feedback_tokens`, and provide custom error templates with `error_template`.

---

## Batch processing

Process hundreds of papers through the same pipeline with configurable parallelism:

```bash
pyconveyor batch pipeline.yaml --input papers.jsonl --output results.jsonl --workers 8
```

```python
from pyconveyor import BatchRunner

runner = BatchRunner("pipeline.yaml", max_workers=8)
for paper_id, result in runner.run(papers):
    if not result.failed:
        save(result.steps["extract"].value)
```

---

## Benchmarking

Measure extraction accuracy against a set of known-correct cases:

```bash
# Create a benchmark case
mkdir -p benchmarks/paper_001
cat > benchmarks/paper_001/input.yaml << 'EOF'
paper: "Smith et al. (2024) demonstrate that CRISPR-Cas9..."
EOF
cat > benchmarks/paper_001/expected.yaml << 'EOF'
extract:
  title: "CRISPR-Cas9 Applications in Gene Therapy"
  authors: ["J. Smith", "A. Chen", "M. Patel"]
EOF

# Run the benchmark
pyconveyor benchmark benchmarks/ --pipeline pipeline.yaml --report report.html
```

Compare two pipeline versions side by side, get per-field accuracy scores, and generate HTML reports with charts and Mermaid graphs. Supports YAML and JSON benchmark files, large inputs via `$file` references, and PDF export.

---

## Ensemble — multi-model consensus

Run multiple models in parallel and auto-merge their outputs:

```yaml
steps:
  - name: extract
    type: ensemble
    schema: schemas:PaperMetadata
    prompt: prompts/extract.j2
    members:
      - model: gpt4o
      - model: claude
        required: false         # pipeline continues if this model fails
    judge:
      model: gpt4o              # reviews all outputs, returns merged result
      condition: all_succeeded
```

Member results are accessible individually as `steps.extract.gpt4o` and `steps.extract.claude`. If the judge is skipped or fails, the first succeeded member's result is returned.

---

## Schema files and code reuse

As pipelines grow, you can move your schemas to a `schemas.py` file:

```python
# schemas.py
from pydantic import BaseModel

class PaperMetadata(BaseModel):
    title: str
    authors: list[str]
    doi: str | None
    publication_year: int

class Classification(BaseModel):
    field: str
    subfield: str | None
    confidence: float
```

Reference them in your pipeline:

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema: schemas:PaperMetadata

  - name: classify
    type: llm
    model: default
    prompt: prompts/classify.j2
    schema: schemas:Classification
```

You can mix inline schemas and Python model references in the same pipeline. Inline schemas are great for getting started; `schemas.py` gives you full Pydantic power when you need cross-field validators, computed properties, or shared model definitions.

---

## Providers

pyconveyor works with any OpenAI-compatible endpoint. Just change `base_url`:

| Provider | Configuration |
|---|---|
| **OpenAI** | `provider: openai_compat` |
| **Anthropic** | `provider: anthropic` + `pip install pyconveyor[anthropic]` |
| **Ollama / vLLM / LM Studio** | `provider: openai_compat` + `base_url: http://localhost:11434/v1` |
| **Custom** | `@register_provider("name")` decorator |
| **Testing** | `provider: mock` — no API calls |

---

## CLI reference

```
pyconveyor init <dir>                  Bootstrap a new project
pyconveyor init <dir> --interactive    Guided setup — define fields interactively
pyconveyor run <pipeline.yaml>         Run a pipeline
pyconveyor validate <pipeline>         Validate without running
pyconveyor batch <pipeline>            Batch process a JSONL file
pyconveyor benchmark <dir>             Benchmark against golden-standard cases
pyconveyor vocab review                Review pending vocabulary suggestions
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
result = runner.run({"paper": "..."})

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

## Load-time validation

`PipelineRunner("pipeline.yaml")` validates everything before spending any tokens — model references, schema imports, expressions, step names. Errors include the YAML line number and "did you mean?" suggestions.

```bash
pyconveyor validate pipeline.yaml
# ✓ pipeline.yaml is valid
```

---

## Versioning policy

The YAML pipeline format is treated as a public API subject to the same semver rules as the Python API. A breaking change to the YAML schema will increment the major version.

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
