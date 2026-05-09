# Vocabulary Fields

`VocabField` constrains a Pydantic model field to a controlled vocabulary, automatically
normalises LLM output to canonical terms, captures the LLM's unconstrained preference,
and grows the vocabulary over time — automatically, via LLM judgment, or through human review.

---

## Motivation

LLMs don't always return your exact controlled terms. They may write `"pet"` instead
of `"PET"`, or `"polylactic acid"` instead of `"PLA"`. `VocabField` handles the
normalisation and records non-canonical values for review or automatic vocabulary growth.

---

## Defining a vocabulary

```python
from pyconveyor.vocab import Vocabulary, VocabField
from pydantic import BaseModel

PlasticVocab = Vocabulary(
    known={"PET", "PE", "PLA", "PP", "PS"},
    label="plastic_type",
    description="Standard resin codes from ISO 1043. Add codes only when a new ISO standard is published.",
    fuzzy_match=True,      # enable edit-distance / substring matching
    case_sensitive=False,  # default: case-insensitive
    growth_policy="human", # "auto" | "human" | "llm" | callable
    capture_ideal=True,    # ask LLM for its unconstrained answer too
    persist="vocabularies/plastic_type.yaml",
)

class ExtractedRecord(BaseModel):
    plastic: str = VocabField(vocab=PlasticVocab, capture_ideal=True)
    quantity: int
```

---

## How normalisation works

When the LLM returns `{"plastic": "pet", "quantity": 3}`:

1. The raw value `"pet"` is looked up in the vocabulary.
2. Case-insensitive exact match → canonical term `"PET"`.
3. The Pydantic model is constructed with `plastic="PET"`.
4. No suggestion is recorded (exact match).

When the LLM returns `{"plastic": "HDPE", "plastic_ideal": "High Density Polyethylene", "quantity": 3}`:

1. `"HDPE"` is not in the vocabulary — no fuzzy match found.
2. The raw value is kept as-is (`plastic="HDPE"`).
3. A `VocabSuggestion` is recorded with `raw_value="HDPE"`, `ideal_value="High Density Polyethylene"`, `match_type="novel"`.
4. The growth policy fires: `"auto"` adds it immediately; `"human"` queues it for CLI review; `"llm"` asks an LLM to decide.

---

## Match types

| Type | Description |
|---|---|
| `exact` | Value matches a canonical term (after case-fold) |
| `fuzzy` | Substring or edit-distance match found; normalised to closest canonical term |
| `novel` | No match; raw value kept; suggestion recorded for review |

---

## Capturing the LLM's ideal answer

When `capture_ideal=True`, pyconveyor automatically appends an instruction to the prompt
asking the LLM to also return `{field}_ideal` alongside the constrained value.

```python
# The LLM returns:
# {"plastic": "PET", "plastic_ideal": "High Density Polyethylene", "quantity": 3}
#
# pyconveyor extracts plastic_ideal before Pydantic validation.
# It is stored in VocabSuggestion.ideal_value — your schema stays unchanged.
```

The ideal value is available in `rctx._vocab_suggestions` and informs the LLM growth policy.

---

## Vocabulary files

The recommended approach is to declare vocabularies in separate YAML files under `vocabularies/`.
This makes term lists human-editable and separates vocabulary concerns from Python schemas.

### `vocabularies/plastic_type.yaml`

```yaml
label: plastic_type
description: "Standard resin codes from ISO 1043."
fuzzy_match: true
case_sensitive: false
growth_policy: human
capture_ideal: true
known:
  - PE
  - PET
  - PLA
  - PP
  - PS
pending:
  - raw_value: HDPE
    ideal_value: "High Density Polyethylene"
    matched_to: null
    match_type: novel
    seen: 3
denied:
  - polylactic acid
```

### `pipeline.yaml`

```yaml
vocabularies:
  plastic_type: vocabularies/plastic_type.yaml

steps:
  - name: extract
    type: llm
    model: default
    schema: schemas:Record
    prompt: prompts/extract.j2
```

### `schemas.py`

```python
from pyconveyor.vocab import VocabField
from pydantic import BaseModel

class Record(BaseModel):
    # Reference by label — resolved from the pipeline's vocabularies: block
    plastic: str = VocabField(vocab="plastic_type")
    quantity: int
```

`pyconveyor init` creates the `vocabularies/` directory automatically.

---

## Prompt injection

pyconveyor automatically appends a vocabulary constraint block to the LLM prompt:

```
---
Vocabulary constraints:
Vocabulary constraint for `plastic_type`: choose from [PE, PET, PLA, PP, PS].
Description: Standard resin codes from ISO 1043.
Do not suggest: [polylactic acid] — these have been explicitly excluded.
Also return `plastic_type_ideal` with your unconstrained best answer (what you would say if not limited to the vocabulary above).
```

### Manual placement with `{{ vocab_hints }}`

For control over where the constraints appear in your prompt, use the `{{ vocab_hints }}`
variable in your Jinja2 template and disable the auto-suffix:

```jinja2
{# prompts/extract.j2 #}
Extract the plastic type from the document below.

{{ vocab_hints }}

Document:
{{ ctx.document }}
```

```yaml
steps:
  - name: extract
    type: llm
    inject_vocab_prompt: false  # disable auto-suffix when using {{ vocab_hints }}
    prompt: prompts/extract.j2
```

---

## Growth policies

### `"auto"` — immediate addition

```python
PlasticVocab = Vocabulary(
    known={"PET", "PE"},
    growth_policy="auto",
    persist="vocabularies/plastic_type.yaml",
)
```

Novel terms are added to `known` immediately after each run. The vocabulary file is updated on disk.

### `"human"` — CLI review

```python
PlasticVocab = Vocabulary(
    known={"PET", "PE"},
    growth_policy="human",
    persist="vocabularies/plastic_type.yaml",
)
```

Novel terms are queued in the `pending` list of the vocab file. Review them with:

```bash
pyconveyor vocab review pipeline.yaml
```

Output:

```
Vocabulary: plastic_type
Description: Standard resin codes from ISO 1043.
Known terms: PE, PET, PLA, PP, PS

Pending suggestions (2):
  1. 'HDPE' (ideal: 'High Density Polyethylene') — novel (seen 3×)
  2. 'polylactic acid' — fuzzy match for 'PLA' (seen 1×)

Enter numbers to accept (comma-separated), 'd<numbers>' to deny, or Enter to skip.
Example: '1,3' to accept; 'd2' to deny #2; '1,3 d2' for both.
> 1 d2
  ✓ Added 'HDPE' to plastic_type
  ✗ Denied 'polylactic acid' in plastic_type
  Saved vocabularies/plastic_type.yaml
```

You can also edit `vocabularies/plastic_type.yaml` directly — move terms from `pending:` to `known:` or `denied:` by hand.

```bash
# Accept all pending without prompting
pyconveyor vocab review pipeline.yaml --auto-accept
```

Denied terms are remembered in the `denied:` list and are not re-surfaced as suggestions. They are also shown to the LLM in the prompt suffix so it avoids them in future runs.

### `"llm"` — LLM-decided

```python
PlasticVocab = Vocabulary(
    known={"PET", "PE"},
    growth_policy="llm",
    growth_policy_model=None,  # use pipeline's default model (or specify by name)
    persist="vocabularies/plastic_type.yaml",
)
```

After each run, pyconveyor fires an LLM call for each novel suggestion:

> *"Given this vocabulary (description, known terms, denied terms), should 'HDPE' (LLM's ideal answer: 'High Density Polyethylene') be added? Reply yes or no."*

The vocabulary's `description` and `denied` list are included to guide the decision.

### Custom callable

```python
def my_policy(suggestion: VocabSuggestion) -> bool:
    # Accept only terms seen ≥ 3 times (tracked in batch runs)
    return True  # or False

PlasticVocab = Vocabulary(known={"PET"}, growth_policy=my_policy)
```

---

## Persistence

Set `persist=True` to use the conventional path `vocabularies/{label}.yaml` relative to
the pipeline directory, or pass an explicit path:

```python
Vocabulary(known={"PET"}, label="plastic_type", persist=True)
# saves to: {pipeline_dir}/vocabularies/plastic_type.yaml

Vocabulary(known={"PET"}, persist="data/vocabs/plastic.yaml")
# saves to: {pipeline_dir}/data/vocabs/plastic.yaml
```

The file is written after every run that produces at least one non-exact suggestion.

---

## Accessing suggestions

```python
runner = PipelineRunner("pipeline.yaml")
rctx = runner.run({"document": "..."})

for suggestion in rctx._vocab_suggestions:
    print(suggestion.field_name, suggestion.raw_value, suggestion.match_type)
    if suggestion.ideal_value:
        print("  LLM's ideal:", suggestion.ideal_value)

# Also available via RunSummary
summary = rctx.summary()
print(summary.vocab_suggestions)
```

`VocabSuggestion` fields:

| Field | Type | Description |
|---|---|---|
| `field_name` | `str` | Pydantic field name |
| `raw_value` | `str` | Original LLM output |
| `matched_to` | `str \| None` | Canonical term (fuzzy) or `None` (novel) |
| `match_type` | `str` | `"exact"`, `"fuzzy"`, or `"novel"` |
| `ideal_value` | `str \| None` | LLM's unconstrained answer (when `capture_ideal=True`) |
| `vocab_label` | `str \| None` | Which vocabulary this came from |

---

## `Vocabulary` configuration

```python
Vocabulary(
    known={"PET", "PE", "PLA"},    # set of canonical terms
    label="plastic_type",           # human-readable label for summaries and file names
    description="...",              # rationale — shown to LLM in prompt suffix
    fuzzy_match=True,               # enable fuzzy matching (default: True)
    case_sensitive=False,           # case-sensitive matching (default: False)
    growth_policy="human",          # "auto" | "human" | "llm" | callable
    growth_policy_model=None,       # model name for "llm" policy (default: pipeline default)
    capture_ideal=False,            # ask LLM for ideal unconstrained value (default: False)
    inject_prompt=True,             # auto-append suffix to LLM prompts (default: True)
    persist=True,                   # save to vocabularies/{label}.yaml
    denied={"polylactic acid"},     # explicitly excluded terms
)
```

Load from a dict or file:

```python
vocab = Vocabulary.from_dict({"known": ["PET", "PE"], "label": "plastic_type"})
vocab = Vocabulary.from_file("vocabularies/plastic_type.yaml")
```

Save manually:

```python
vocab.save("vocabularies/plastic_type.yaml")
```

---

## Standalone usage

`apply_vocab` can be used without the pipeline runner:

```python
from pyconveyor.vocab import Vocabulary, apply_vocab

vocab = Vocabulary(known={"PET", "PE"})
stored, novel, matched, suggestion = apply_vocab("pet", vocab, "plastic")
# stored="PET", novel=None, matched=True, suggestion=None
```
