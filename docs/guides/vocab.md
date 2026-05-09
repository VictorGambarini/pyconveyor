# Vocabulary Fields

`VocabField` constrains a Pydantic model field to a controlled vocabulary and
automatically normalises LLM output to canonical terms.

---

## Motivation

LLMs don't always return your exact controlled terms. They may write `"pet"` instead
of `"PET"`, or `"polylactic acid"` instead of `"PLA"`. `VocabField` handles the
normalisation and records non-canonical values for human review.

---

## Defining a vocabulary

```python
from pyconveyor.vocab import Vocabulary, VocabField
from pydantic import BaseModel

PlasticVocab = Vocabulary(
    known={"PET", "PE", "PLA", "PP", "PS"},
    label="plastic_type",
    fuzzy_match=True,      # enable edit-distance / substring matching
    case_sensitive=False,  # default: case-insensitive
)

class ExtractedRecord(BaseModel):
    plastic: str = VocabField(vocab=PlasticVocab)
    quantity: int
```

---

## How normalisation works

When the LLM returns `{"plastic": "pet", "quantity": 3}`:

1. The raw value `"pet"` is looked up in the vocabulary.
2. Case-insensitive exact match → canonical term `"PET"`.
3. The Pydantic model is constructed with `plastic="PET"`.
4. No suggestion is recorded (exact match).

When the LLM returns `{"plastic": "HDPE", "quantity": 3}`:

1. `"HDPE"` is not in the vocabulary.
2. No fuzzy match found.
3. The raw value is kept as-is (`plastic="HDPE"`).
4. A `VocabSuggestion` is recorded: `{field_name: "plastic", raw_value: "HDPE", match_type: "novel"}`.

---

## Match types

| Type | Description |
|---|---|
| `exact` | Value matches a canonical term (after case-fold) |
| `fuzzy` | Substring or edit-distance match found; normalised to closest canonical term |
| `novel` | No match; raw value kept; suggestion recorded for review |

---

## Accessing suggestions

Suggestions are available on the `RunContext` after the run:

```python
runner = PipelineRunner("pipeline.yaml")
rctx = runner.run({"document": "..."})

for suggestion in rctx._vocab_suggestions:
    print(suggestion.field_name, suggestion.raw_value, suggestion.match_type)

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

---

## `Vocabulary` configuration

```python
Vocabulary(
    known={"PET", "PE", "PLA"},   # set of canonical terms
    label="plastic_type",          # human-readable label for summaries
    fuzzy_match=True,              # enable fuzzy matching (default: True)
    case_sensitive=False,          # case-sensitive matching (default: False)
)
```

Load from a dict (e.g. from YAML):

```python
vocab = Vocabulary.from_dict({
    "known": ["PET", "PE", "PLA"],
    "fuzzy_match": True,
    "case_sensitive": False,
})
```

---

## Pipeline YAML vocabularies

You can also define vocabularies in `pipeline.yaml` and reference them in Jinja2 prompts:

```yaml
vocabularies:
  plastic_type:
    known: [PET, PE, PLA, PP, PS]
    fuzzy_match: true

steps:
  - name: extract
    type: llm
    prompt: prompts/extract.j2
    schema: schemas:Record
```

In the prompt template, `{{ vocab.plastic_type.known | join(", ") }}` renders the term list.
The `VocabField` integration applies automatically when the Pydantic schema uses `VocabField`.

---

## Standalone usage

`apply_vocab` can be used without the pipeline runner:

```python
from pyconveyor.vocab import Vocabulary, apply_vocab

vocab = Vocabulary(known={"PET", "PE"})
stored, novel, matched, suggestion = apply_vocab("pet", vocab, "plastic")
# stored="PET", novel=None, matched=True, suggestion=None
```
