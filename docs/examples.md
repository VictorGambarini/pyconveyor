# Examples

Working examples for common pyconveyor use cases.

---

## Single-step extraction

The minimal pipeline: one LLM call, one schema, one result.

**`schemas.py`**
```python
from pydantic import BaseModel
from typing import List

class ArticleSummary(BaseModel):
    title: str
    authors: List[str]
    key_findings: List[str]
    methodology: str
```

**`prompts/summarise.j2`**
```jinja2
Summarise the following scientific article.

Article:
{{ ctx.text }}

Return a JSON object with:
- "title": the article title
- "authors": list of author names
- "key_findings": up to 5 key findings as short strings
- "methodology": one sentence describing the methodology
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
  - name: summarise
    type: llm
    model: default
    prompt: prompts/summarise.j2
    schema: schemas:ArticleSummary
    max_attempts: 3
```

**`run.py`**
```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("pipeline.yaml")
result = runner.run({"text": open("article.txt").read()})

if result.failed:
    print("Failed:", result.failure_state)
else:
    summary = result.steps["summarise"].value
    print(summary.title)
    print(summary.key_findings)
```

**CLI:**
```bash
pyconveyor run pipeline.yaml --input '{"text": "..."}'
```

---

## Dual-model reconciliation

Two models extract independently; a merge step arbitrates disagreements. This is pyconveyor's primary/reviewer pattern.

**`schemas.py`**
```python
from pydantic import BaseModel
from typing import List, Optional

class Extraction(BaseModel):
    classification: str
    confidence: float
    notes: Optional[str] = None
```

**`steps.py`**
```python
from schemas import Extraction
from typing import Optional

def reconcile(primary: Optional[Extraction], reviewer: Optional[Extraction]) -> Extraction:
    if reviewer is None:
        return primary

    if primary.classification == reviewer.classification:
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
    required: false   # pipeline continues if reviewer is not configured

steps:
  - name: extract
    type: parallel
    steps:
      - name: primary
        type: llm
        model: primary
        prompt: prompts/classify.j2
        schema: schemas:Extraction
        max_attempts: 3

      - name: reviewer
        type: llm
        model: reviewer
        prompt: prompts/classify.j2
        schema: schemas:Extraction
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
result = runner.run({"document": "..."})

final = result.steps["final"].value
print(f"Classification: {final.classification} (confidence: {final.confidence})")
```

---

## Ensemble extraction with auto-judge

Run two models in parallel and let a third model merge their outputs into one result. No glue code needed.

**`schemas.py`**
```python
from pydantic import BaseModel
from typing import Optional

class Extraction(BaseModel):
    classification: str
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
        required: false      # pipeline continues if this model is unavailable
    judge:
      model: gpt4o
      condition: all_succeeded   # only merge when both models returned results
```

**`run.py`**
```python
from pyconveyor import PipelineRunner

runner = PipelineRunner("pipeline.yaml")
result = runner.run({"document": "..."})

# The merged result (judge output, or first-member fallback)
final = result.steps["extract"].value
print(f"Classification: {final.classification} (confidence: {final.confidence})")

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
    condition: "{{ ctx.document is not none }}"

  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema: schemas:ExtractionResult
    max_attempts: 3
    on_error: continue         # don't abort pipeline on extraction failure
    on_failure: steps:log_failure

  - name: save
    type: io
    fn: steps:save_result
    inputs:
      result: "{{ steps.extract.value }}"
      doc_id: "{{ ctx.doc_id }}"
    condition: "{{ steps.extract.value is not none }}"
```

**`steps.py`**
```python
from typing import Optional
from schemas import ExtractionResult

def log_failure(step_name, exception, rctx):
    print(f"Step {step_name} failed: {exception}")

def save_result(result: Optional[ExtractionResult], doc_id: str):
    if result is None:
        print(f"Skipping save for {doc_id}: extraction failed")
        return
    # persist result...
    print(f"Saved {doc_id}: {result.title}")
```

---

## Conditional branching

Route to a fast or thorough extraction based on document length.

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
    if: "{{ len(ctx.document) < 5000 }}"
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
        {"document": "Test document"},
        model_overrides={
            "default": {
                "provider": "mock",
                "response": '{"title": "Test", "key_points": ["Point one"]}',
            }
        }
    )
    assert not result.failed
    extraction = result.steps["extract"].value
    assert extraction.title == "Test"
    assert len(extraction.key_points) == 1
```
