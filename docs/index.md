# pyconveyor

**Deterministic YAML pipeline engine for structured LLM extraction.**

pyconveyor lets you describe an extraction workflow in YAML, write prompts in Jinja2, and define step logic in plain Python. The runner handles model calls, retries, schema validation, parallel execution, and structured result summaries.

```bash
pip install pyconveyor
```

```yaml
# pipeline.yaml
models:
  default:
    provider: openai_compat
    base_url: ${OPENAI_BASE_URL}
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o-mini

steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema: schemas:ExtractionResult
    max_attempts: 3
```

```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("pipeline.yaml")
result = runner.run({"document": "Full text here…"})

if not result.failed:
    print(result.steps["extract"].value)
```

---

## Why pyconveyor?

The real competition is not LangChain or LlamaIndex. It is:

- **Ad-hoc Python scripts** that break when the model output format shifts
- **Jupyter notebooks** that are not reproducible and cannot be scheduled
- **Bash glue pipelines** with no schema guarantees
- **Fragile prompt loops** rewritten from scratch for every new extraction task

pyconveyor makes **reproducible extraction, reliable retries, schema-safe outputs, and observable runs** simpler than handwritten glue code.

---

## Key features

| Feature | What it means |
|---|---|
| **YAML as a versioned API** | Breaking schema changes require a semver major bump |
| **OpenAI-compat-first** | Works with Ollama, vLLM, LM Studio, and any hosted endpoint |
| **Extraction-focused** | Optimised for classification, annotation, and structured record extraction |
| **Explicit DAG** | Every step, dependency, and control flow branch is visible in one YAML file |
| **Self-correcting retries** | Schema and parse errors are fed back to the model so it can fix itself |
| **Comprehensible in one sitting** | The entire runner is one file; the YAML format has a one-page reference |

---

## What pyconveyor is not

pyconveyor does not use the words `agent`, `autonomous`, `AI workflow platform`, `tool calling`, `memory`, or `RAG`. These describe a different audience and a different set of problems.

pyconveyor is: `deterministic`, `reproducible`, `schema-driven`, `extraction pipelines`, `structured outputs`, `multi-model reconciliation`, `research workflows`.

---

## Navigation

- **[Quickstart](quickstart.md)** — up and running in 5 minutes
- **[Concepts](concepts.md)** — how pipelines, steps, and context fit together
- **[Step Types](guides/step-types.md)** — `llm`, `transform`, `validate`, `io`, `parallel`, `condition`
- **[Validation Feedback](guides/validation-feedback.md)** — self-correcting retry loops
- **[YAML Schema](reference/schema.md)** — every field, type, and default
- **[CLI Reference](reference/cli.md)** — `init`, `run`, `validate`, `schema`, `visualise`
- **[Examples](examples.md)** — single-step extraction, dual-model reconciliation
