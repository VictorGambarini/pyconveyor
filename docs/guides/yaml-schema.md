# YAML Schema

pyconveyor lets you define the shape of LLM output entirely in YAML — no Python files required. Field descriptions become part of the prompt automatically.

## Simple inline schema

The quickest way to add a schema is to write field names and type strings directly inside a step:

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      title: str
      authors: list[str]
      doi: str | None
      publication_year: int
    max_attempts: 3
```

Supported types:

| Type string | Python type |
|---|---|
| `str` | `str` |
| `int` | `int` |
| `float` | `float` |
| `bool` | `bool` |
| `str \| None` | `Optional[str]` |
| `int \| None` | `Optional[int]` |
| `float \| None` | `Optional[float]` |
| `bool \| None` | `Optional[bool]` |
| `list[str]` | `list[str]` |
| `list[int]` | `list[int]` |
| `list[float]` | `list[float]` |
| `list[bool]` | `list[bool]` |
| `dict[str, str]` | `dict[str, str]` |
| `dict[str, int]` | `dict[str, int]` |

For anything more complex — unions, generics, custom validators — use a Pydantic model (see [When to use Python models](#when-to-use-python-models) below).

---

## Rich field format

Add a description, constraints, and failure behaviour by expanding each field from a type string to a dict:

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      title:
        type: str
        description: "Paper title exactly as written, including subtitle."
        min_length: 1
      authors:
        type: list[str]
        description: "All author names in publication order."
        min_items: 1
      doi:
        type: str | None
        description: "DOI if listed. Null if not found."
        pattern: "^10\\.[0-9]{4,}/.+$"
        on_fail: null
      publication_year:
        type: int
        description: "Four-digit year of publication."
```

### Rich field keys

| Key | Required | Description |
|---|---|---|
| `type` | yes | Type string (same as the simple format) |
| `description` | no | Human-readable description. Injected into the LLM prompt automatically. |
| `pattern` | no | Regex pattern. The value must match the full string. |
| `min_length` | no | Minimum string length (strings only). |
| `max_length` | no | Maximum string length (strings only). |
| `min_items` | no | Minimum list length (lists only). |
| `max_items` | no | Maximum list length (lists only). |
| `on_fail` | no | What to do when a constraint is violated: `error` (default), `null`, or `warn`. |
| `vocab` | no | Filename in `vocabularies/` directory (e.g. `organism` → `vocabularies/organism.yaml`) or inline dict `{terms: [...], description: ...}`. Vocab normalisation runs automatically — fuzzy matches are normalised, novel values are captured as suggestions. |

### `on_fail` values

| Value | Behaviour |
|---|---|
| `error` (default) | Raise a `ValidationError` — triggers a retry if `max_attempts > 1` |
| `null` | Silently coerce the invalid value to `None` |
| `warn` | Log a warning and keep the value as-is |

Use `on_fail: null` for fields where bad model output is expected sometimes and a null is acceptable:

```yaml
accession_id:
  type: str | None
  description: "Database accession (e.g. WP_123456). Null if not reported."
  pattern: "^[A-Za-z0-9][A-Za-z0-9_.]{2,39}$"
  on_fail: null       # bad accession → null, no retry
```

Use `on_fail: error` (the default) for fields that must be correct:

```yaml
organism_name:
  type: str
  description: "Genus + species binomial."
  min_length: 1      # empty string → retry
```

---

## Nested objects

Use `type: list` with an `items:` block to define a list of structured objects:

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      records:
        type: list
        description: "One record per organism mentioned in the paper."
        min_items: 1
        items:
          organism_name:
            type: str
            description: "Genus + species binomial."
            min_length: 1
          plastic:
            type: str
            description: "ISO polymer code (e.g. PET, PLA)."
          confidence:
            type: float
            description: "Extraction confidence 0.0–1.0."
```

Items can themselves have `type: list` with an `items:` block for deeper nesting, though two levels is enough for almost all extraction tasks.

---

## Top-level `schema:` block

For complex schemas shared across multiple steps, define the schema at the top level and reference it by name:

```yaml
schema:
  records:
    type: list
    description: "One record per item."
    min_items: 1
    items:
      name:
        type: str
        description: "Item name."
      value:
        type: float
        description: "Numeric value."
  metadata:
    type: str
    description: "Document-level metadata."

steps:
  - name: extract
    type: ensemble
    schema: src.extractor:ExtractionResult  # still references Python class
    prompt: prompts/extract.j2
    members:
      - model: model_a
        name: primary
        required: true
      - model: model_b
        name: reviewer
        required: false
    judge:
      model: model_b
      condition: all_succeeded
```

The top-level `schema:` block is typically loaded by your application code:

```python
import yaml
from pathlib import Path
from pyconveyor.schema_builder import yaml_dict_to_model

raw = yaml.safe_load(Path("pipeline.yaml").read_text())
ExtractionResult = yaml_dict_to_model("ExtractionResult", raw["schema"])
```

This keeps the schema as the single source of truth: edit the YAML and the Pydantic model updates automatically.

---

## How descriptions reach the prompt

When a field has a `description`, pyconveyor renders a schema hint and makes it available as `{{ schema_hint }}` in your Jinja2 prompt templates:

```jinja2
{# prompts/extract.j2 #}
You are a scientific literature extractor.

{{ schema_hint }}

---
{{ ctx.document }}
```

`schema_hint` renders as:

```
Return a JSON object with the following fields:
- "records": array of objects (required)
    One record per organism mentioned in the paper.
    - "organism_name": string (required)
        Genus + species binomial.
    - "plastic": string (required)
        ISO polymer code (e.g. PET, PLA).
    - "confidence": number (required)
        Extraction confidence 0.0–1.0.
- "metadata": string (required)
    Document-level metadata.
```

Nested fields are indented one level deeper than their parent. Fields without descriptions appear as a single line.

If `{{ schema_hint }}` is absent from the template, no hint is injected — the schema is still enforced for validation and retries, just not described in the prompt.

---

## Using Pydantic models directly

YAML schemas cover the common cases. For anything beyond what YAML supports, pass a Pydantic `BaseModel` subclass as the schema instead:

```yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema: schemas:ExtractionResult   # module:ClassName
```

```python
# schemas.py
from pydantic import BaseModel, field_validator
from typing import Optional

class EntryRecord(BaseModel):
    organism: str
    confidence: float

    @field_validator("confidence")
    @classmethod
    def _range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence out of range")
        return v

class ExtractionResult(BaseModel):
    entries: list[EntryRecord]
    supplements_required: bool
```

`model_to_schema_hint()` works with hand-written models too — any field defined with `Field(description=...)` gets rendered in `{{ schema_hint }}`:

```python
from pydantic import BaseModel, Field

class ExtractionResult(BaseModel):
    entries: list[EntryRecord] = Field(..., description="One entry per organism.")
    supplements_required: bool = Field(..., description="True if key data is only in supplements.")
```

---

## When to use Python models

Prefer YAML schemas when:

- You want the schema to be readable and editable without touching Python
- You need field descriptions to appear in prompts
- Simple type + constraint combinations are sufficient (`min_length`, `pattern`, `on_fail`)

Use Python Pydantic models when:

- You need cross-field validation (`@model_validator`)
- You need computed fields or custom coercion beyond `on_fail`
- You want to reuse the model in downstream code (type annotations, serialisation)
- Your schema is deeply nested or recursive

Both approaches can be mixed freely — a Pydantic model can reference YAML-generated sub-models and vice versa.
