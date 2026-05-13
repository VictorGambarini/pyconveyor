# Examples

Working examples for common pyconveyor use cases.

---

## Single-step extraction

The minimal pipeline: one LLM call, one schema, one result.

**`schemas.py`**
```python
from pydantic import BaseModel
from typing import List, Optional

class PaperMetadata(BaseModel):
    title: str
    authors: List[str]
    key_findings: List[str]
    methodology: str
    doi: Optional[str] = None
```

**`prompts/extract.j2`**
```jinja2
Extract structured metadata from the following scientific paper.

Paper:
{{ ctx.paper }}

{{ schema_hint }}
```

**`pipeline.yaml`**
```yaml
models:
  default:
    provider: openai_compat
    base_url: ${OPENAI_BASE_URL}
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o-mini
    timeout:  120

steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema: schemas:PaperMetadata
    max_attempts: 3
```

**`run.py`**
```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("pipeline.yaml")
result = runner.run({"paper": open("paper.md").read()})

if result.failed:
    print("Failed:", result.failure_state)
else:
    meta = result.steps["extract"].value
    print(meta.title)
    print(meta.key_findings)
```

**CLI:**
```bash
pyconveyor run pipeline.yaml --input '{"paper": "..."}'
```

---

## Multi-step extraction with classification

Extract metadata, then classify the paper into a research field — all in one pipeline.

**`pipeline.yaml`**
```yaml
models:
  default:
    provider: openai_compat
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o-mini
    timeout:  120

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

**`prompts/classify.j2`**
```jinja2
Classify this paper into a research field.

Title: {{ steps.extract.title }}
Abstract: {{ steps.extract.abstract }}

Return:
- "field": primary field (e.g. "materials science", "molecular biology")
- "subfield": more specific if identifiable
- "confidence": your confidence 0.0-1.0
```

---

## Controlled vocabulary on fields

Constrain extraction to known terms with automatic fuzzy matching.

**`vocabularies/organism.yaml`**
```yaml
known:
  - Escherichia coli
  - Saccharomyces cerevisiae
  - Bacillus subtilis
  - Pseudomonas aeruginosa
  - Staphylococcus aureus
label: organism
growth_policy: auto
```

**`vocabularies/method.yaml`**
```yaml
known:
  - PCR
  - Western blot
  - ELISA
  - Mass spectrometry
  - RNA-seq
  - CRISPR-Cas9
  - Flow cytometry
label: method
growth_policy: human
```

**`pipeline.yaml`**
```yaml
models:
  default:
    provider: openai_compat
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o-mini
    timeout:  120

steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      organism:
        type: str
        description: "Primary organism studied."
        vocab: organism
      method:
        type: str
        description: "Primary experimental method used."
        vocab: method
      finding: str
    max_attempts: 3
```

The `organism` vocabulary uses `growth_policy: auto` — close matches (like "E. coli" → "Escherichia coli") are accepted immediately. The `method` vocabulary uses `growth_policy: human` — novel methods are queued for CLI review.

```bash
pyconveyor vocab review
```

---

## Dual-model reconciliation

Two models extract independently; a merge step arbitrates disagreements.

**`schemas.py`**
```python
from pydantic import BaseModel
from typing import Optional

class Classification(BaseModel):
    field: str
    confidence: float
    notes: Optional[str] = None
```

**`steps.py`**
```python
from schemas import Classification
from typing import Optional

def reconcile(primary: Optional[Classification], reviewer: Optional[Classification]) -> Classification:
    if reviewer is None:
        return primary
    if primary.field == reviewer.field:
        return primary
    # Disagree — take the higher-confidence result
    return primary if primary.confidence >= reviewer.confidence else reviewer
```

**`pipeline.yaml`**
```yaml
models:
  primary:
    provider: openai_compat
    base_url: ${PRIMARY_BASE_URL}
    api_key:  ${PRIMARY_API_KEY}
    model:    gpt-4o
    timeout:  120

  reviewer:
    provider: openai_compat
    base_url: ${REVIEWER_BASE_URL}
    api_key:  ${REVIEWER_API_KEY}
    model:    gpt-4o-mini
    timeout:  120
    required: false

steps:
  - name: extract
    type: parallel
    steps:
      - name: primary
        type: llm
        model: primary
        prompt: prompts/classify.j2
        schema: schemas:Classification
        max_attempts: 3

      - name: reviewer
        type: llm
        model: reviewer
        prompt: prompts/classify.j2
        schema: schemas:Classification
        max_attempts: 2
        required: false

  - name: final
    type: transform
    fn: steps:reconcile
    inputs:
      primary:  "{{ steps.extract.primary }}"
      reviewer: "{{ steps.extract.reviewer }}"
```

**`run.py`**
```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("pipeline.yaml")
result = runner.run({"paper": "..."})

final = result.steps["final"].value
print(f"Field: {final.field} (confidence: {final.confidence})")
```

---

## Ensemble extraction with auto-judge

Run two models in parallel and let a third model merge their outputs. No glue code needed.

**`schemas.py`**
```python
from pydantic import BaseModel
from typing import Optional

class Extraction(BaseModel):
    field: str
    confidence: float
    notes: Optional[str] = None
```

**`pipeline.yaml`**
```yaml
models:
  gpt4o:
    provider: openai_compat
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o
    timeout:  120

  claude:
    provider: anthropic
    api_key:  ${ANTHROPIC_API_KEY}
    model:    claude-opus-4-7
    timeout:  120

steps:
  - name: extract
    type: ensemble
    schema: schemas:Extraction
    prompt: prompts/classify.j2
    members:
      - model: gpt4o
        name: primary
      - model: claude
        name: reviewer
        required: false
    judge:
      model: gpt4o
      condition: all_succeeded
```

**`run.py`**
```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("pipeline.yaml")
result = runner.run({"paper": "..."})

# The merged result (judge output, or first-member fallback)
final = result.steps["extract"].value
print(f"Field: {final.field} (confidence: {final.confidence})")

# Individual member results are also available
primary  = result.steps["extract.primary"].value
reviewer = result.steps["extract.reviewer"].value
```

Compare this to the [Dual-model reconciliation](#dual-model-reconciliation) example above, which requires a separate `transform` step for merging. `ensemble` handles the merge automatically.

---

## Multi-stage pipeline with error handling

A three-step pipeline: extract → validate → save. The save step runs even if validation produces warnings.

**`pipeline.yaml`**
```yaml
models:
  default:
    provider: openai_compat
    base_url: ${OPENAI_BASE_URL}
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o-mini
    timeout:  120

steps:
  - name: check_input
    type: validate
    condition: "{{ ctx.paper is not none }}"

  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema: schemas:ExtractionResult
    max_attempts: 3
    on_error: continue
    on_failure: steps:log_failure

  - name: save
    type: io
    fn: steps:save_result
    inputs:
      result: "{{ steps.extract.value }}"
      paper_id: "{{ ctx.paper_id }}"
    condition: "{{ steps.extract.value is not none }}"
```

**`steps.py`**
```python
from typing import Optional
from schemas import ExtractionResult

def log_failure(step_name, exception, rctx):
    print(f"Step {step_name} failed: {exception}")

def save_result(result: Optional[ExtractionResult], paper_id: str):
    if result is None:
        print(f"Skipping save for {paper_id}: extraction failed")
        return
    print(f"Saved {paper_id}: {result.title}")
```

---

## Conditional branching

Route to a fast or thorough extraction based on paper length.

**`pipeline.yaml`**
```yaml
models:
  fast:
    provider: openai_compat
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o-mini
    timeout:  60

  thorough:
    provider: openai_compat
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o
    timeout:  300

steps:
  - name: route
    type: condition
    if: "{{ len(ctx.paper) < 5000 }}"
    then:
      - name: extract
        type: llm
        model: fast
        prompt: prompts/extract_fast.j2
        schema: schemas:ExtractionResult
    else:
      - name: extract
        type: llm
        model: thorough
        prompt: prompts/extract_full.j2
        schema: schemas:ExtractionResult
        max_attempts: 5
```

---

## Dry run

Validate the pipeline logic and expressions without spending tokens:

```bash
pyconveyor run pipeline.yaml --input input.json --dry-run
```

LLM steps return `None`; transform and io steps still execute. Useful for checking that all expressions resolve correctly and all referenced functions are importable.

---

## Unit testing with the `mock` provider

Test pipeline logic without API calls:

```python
# tests/test_pipeline.py
import pytest
from pyconveyor import PipelineRunner

def test_extraction_pipeline():
    runner = PipelineRunner("pipeline.yaml")
    result = runner.run(
        {"paper": "Smith et al. demonstrate..."},
        model_overrides={
            "default": {
                "provider": "mock",
                "response": '{"title": "Test Paper", "key_findings": ["Finding one"]}',
            }
        }
    )
    assert not result.failed
    extraction = result.steps["extract"].value
    assert extraction.title == "Test Paper"
    assert len(extraction.key_findings) == 1
```
