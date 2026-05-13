# pyconveyor

**Deterministic YAML pipeline engine for structured LLM extraction.**

pyconveyor lets you describe an extraction workflow in YAML, write prompts in Jinja2, and define step logic in plain Python. The runner handles model calls, retries, schema validation, parallel execution, and structured result summaries.

```bash
pip install pyconveyor
```

---

## Get started in 60 seconds

```bash
# 1. Bootstrap a project (interactive — no Python files needed)
pyconveyor init my_pipeline/ --interactive
cd my_pipeline/

# 2. Set your API key
export OPENAI_API_KEY=sk-...

# 3. Run
pyconveyor run pipeline.yaml --input '{"paper": "Smith et al. demonstrate that..."}'
```

Or go deeper with the **[Quickstart guide →](quickstart.md)**

---

## Key features

| Feature | What it means |
|---|---|
| **YAML-first** | The whole pipeline — models, steps, schemas, prompts — lives in one YAML file |
| **CLI-first** | `pyconveyor init`, `run`, `batch`, `benchmark` — no Python needed to get started |
| **OpenAI-compat-first** | Works with Ollama, vLLM, LM Studio, and any hosted endpoint |
| **Self-correcting retries** | Schema and parse errors are fed back to the model so it can fix itself |
| **Vocabularies on fields** | Declare controlled vocabularies on schema fields; automatic fuzzy matching and suggestion capture |
| **Benchmarking built in** | Compare pipeline versions against golden-standard cases; get per-step accuracy |
| **HTML/PDF reports** | One command produces a shareable report with tables, graphs, and charts |
| **Extraction-focused** | Optimised for classification, annotation, and structured record extraction |
| **Explicit DAG** | Every step, dependency, and control flow branch is visible in one YAML file |
| **Comprehensible in one sitting** | The entire runner is one file; the YAML format has a one-page reference |

---

## Navigation

**Getting started**

- **[Quickstart](quickstart.md)** — up and running in 5 minutes
- **[Concepts](concepts.md)** — how pipelines, steps, and context fit together

**Guides**

- **[Step Types](guides/step-types.md)** — `llm`, `ensemble`, `transform`, `validate`, `io`, `parallel`, `condition`
- **[YAML Schema](guides/yaml-schema.md)** — inline schemas, field descriptions, validators, nested objects
- **[Validation Feedback](guides/validation-feedback.md)** — self-correcting retry loops
- **[Batch Processing](guides/batch.md)** — process thousands of documents in parallel
- **[Benchmarking](guides/benchmarking.md)** — measure accuracy, compare pipelines, generate reports
- **[Vocabulary Fields](guides/vocab.md)** — constrained extraction with fuzzy matching
- **[Response Caching](guides/caching.md)** — speed up development with cached LLM responses
- **[Providers](guides/providers.md)** — OpenAI, Anthropic, Ollama, custom providers
- **[Hooks](guides/hooks.md)** — callbacks for observability and side effects

**Reference**

- **[YAML Schema](reference/schema.md)** — every field, type, and default
- **[CLI Reference](reference/cli.md)** — `init`, `run`, `batch`, `validate`, `schema`, `benchmark`, `visualise`, `vocab review`
