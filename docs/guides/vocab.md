# Vocabulary Fields

Vocabularies constrain a Pydantic model field to a known set of terms, automatically normalise fuzzy matches, capture novel values for review, and grow over time.

---

## Motivation

LLMs don't always return your exact controlled terms. They may write `"E. coli"` instead of `"Escherichia coli"`, or `"gene knockout"` instead of `"knockout"`. Vocabulary fields handle the normalisation and record non-canonical values for review or automatic vocabulary growth.

---

## File-based vocabularies

The recommended approach: define vocabularies as YAML files in a `vocabularies/` directory next to your pipeline. They're loaded automatically and referenced by filename on schema fields.

### Directory layout

```
your_project/
├── pipeline.yaml
├── vocabularies/
│   ├── organism.yaml
│   └── method.yaml
└── prompts/
    └── extract.j2
```

### Vocabulary file format

```yaml
# vocabularies/organism.yaml
label: organism
description: "Genus + species binomial names from standard taxonomy databases."
fuzzy_match: true
case_sensitive: false
growth_policy: auto
capture_ideal: true
known:
  - Escherichia coli
  - Saccharomyces cerevisiae
  - Bacillus subtilis
  - Pseudomonas aeruginosa
  - Staphylococcus aureus
```

### Referencing on a schema field

```yaml
# pipeline.yaml
steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
      organism:
        type: str
        description: "Primary organism studied."
        vocab: organism     # loads vocabularies/organism.yaml
      method:
        type: str
        description: "Primary experimental method."
        vocab: method       # loads vocabularies/method.yaml
```

The filename (without `.yaml`) is the key. pyconveyor loads all `.yaml` and `.yml` files from the `vocabularies/` directory at startup — no pipeline-level declaration needed.

### Inline vocabs

For small, ad-hoc vocabularies, define them directly on the field:

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
      description: "Controlled vocabulary for study type."
```

Inline vocabs are restricted to `growth_policy: auto` only — no `persist`, no `human`, no `llm`. Use file-based vocabs for those features.

---

## How normalisation works

When the LLM returns `{"organism": "E. coli"}`:

1. The raw value `"E. coli"` is looked up in the vocabulary.
2. Fuzzy matching finds `"Escherichia coli"` as the closest canonical term.
3. The value is normalised to `organism="Escherichia coli"`.
4. A `VocabSuggestion` is recorded with `match_type="fuzzy"`.

When the LLM returns `{"organism": "Lactobacillus casei"}`:

1. `"Lactobacillus casei"` is not in the vocabulary — no match found.
2. The raw value is kept as-is.
3. A `VocabSuggestion` is recorded with `match_type="novel"`.
4. The growth policy fires: `"auto"` adds it immediately; `"human"` queues for CLI review.

Normalisation is baked into the Pydantic model via `model_validator(mode='before')` — it runs before constraint checks, so vocab normalisation and field constraints compose cleanly.

---

## Match types

| Type | Description |
|---|---|
| `exact` | Value matches a canonical term (after case-fold) |
| `fuzzy` | Substring or edit-distance match found; normalised to closest canonical term |
| `novel` | No match; raw value kept; suggestion recorded for review |

---

## Capturing the LLM's ideal answer

When `capture_ideal: true` is set, pyconveyor asks the LLM to also return `{field}_ideal` alongside the constrained value. The ideal value is extracted before Pydantic validation and stored in `VocabSuggestion.ideal_value`.

---

## Prompt injection

pyconveyor automatically appends vocabulary constraints to the LLM prompt for all schema-referenced vocabs:

```
---
Vocabulary constraints:
Vocabulary constraint for `organism`: choose from [Escherichia coli, Saccharomyces cerevisiae, ...].
Description: Genus + species binomial names from standard taxonomy databases.
```

Only vocabs referenced by the step's schema fields are injected — not all loaded vocabs.

### Manual placement with `{{ vocab_hints }}`

For control over where vocab constraints appear in your prompt:

```jinja2
{# prompts/extract.j2 #}
Extract details from the paper below.

{{ vocab_hints }}

Paper:
{{ ctx.paper }}
```

```yaml
steps:
  - name: extract
    type: llm
    inject_vocab_prompt: false  # disable auto-suffix when using {{ vocab_hints }}
    prompt: prompts/extract.j2
    schema:
      organism:
        type: str
        vocab: organism
```

---

## Growth policies

### `"auto"` — immediate addition

Novel terms are added to `known` immediately after each run. Best for well-bounded vocabularies where new terms are always valid.

```yaml
# vocabularies/organism.yaml
growth_policy: auto
known:
  - Escherichia coli
  - Saccharomyces cerevisiae
```

### `"human"` — CLI review

Novel terms are queued in the `pending` list. Review them with:

```bash
pyconveyor vocab review
```

The command scans the `vocabularies/` directory and presents pending suggestions:

```
Vocabulary: method
Description: Primary experimental methods in molecular biology.
Known terms: PCR, Western blot, ELISA, Mass spectrometry, RNA-seq

Pending suggestions (2):
  1. 'CRISPR-Cas9' (ideal: 'CRISPR-Cas9 genome editing') — novel (seen 3×)
  2. 'immunoblotting' — fuzzy match for 'Western blot' (seen 1×)

Enter numbers to accept (comma-separated), 'd<numbers>' to deny, or Enter to skip.
Example: '1,3' to accept; 'd2' to deny #2; '1,3 d2' for both.
> 1 d2
  ✓ Added 'CRISPR-Cas9' to method
  ✗ Denied 'immunoblotting' in method
  Saved vocabularies/method.yaml
```

Auto-accept all pending without prompting:

```bash
pyconveyor vocab review --auto-accept
```

You can also edit the vocab YAML file directly — move terms from `pending:` to `known:` or `denied:` by hand.

### `"llm"` — LLM-decided

After each run, pyconveyor fires an LLM call for each novel suggestion:

> *"Given this vocabulary (description, known terms, denied terms), should 'CRISPR-Cas9' be added? Reply yes or no."*

```yaml
# vocabularies/method.yaml
growth_policy: llm
growth_policy_model: null  # use pipeline's default model (or specify by name)
```

The vocabulary's `description` and `denied` list are included to guide the decision.

### Custom callable

```python
def my_policy(suggestion: VocabSuggestion) -> bool:
    # Accept only terms seen ≥ 3 times
    return True  # or False

vocab = Vocabulary(known={"PCR"}, growth_policy=my_policy)
```

---

## Persistence

File-based vocabs with `persist: true` save back to their file after runs that produce suggestions:

```yaml
# vocabularies/organism.yaml
growth_policy: auto
persist: true
known:
  - Escherichia coli
```

---

## Accessing suggestions

```python
runner = PipelineRunner("pipeline.yaml")
rctx = runner.run({"paper": "..."})

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

## Python API (for schemas.py users)

If you're using `schemas.py` with Pydantic models, you can wire up vocabs in Python:

```python
from pyconveyor.vocab import Vocabulary, VocabField
from pydantic import BaseModel

OrganismVocab = Vocabulary(
    known={"Escherichia coli", "Saccharomyces cerevisiae", "Bacillus subtilis"},
    label="organism",
    growth_policy="auto",
)

class ExtractionRecord(BaseModel):
    organism: str = VocabField(vocab=OrganismVocab)
    quantity: int
```

Load from a file:

```python
vocab = Vocabulary.from_file("vocabularies/organism.yaml")
```

---

## Vocabulary YAML reference

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `known` | list[string] | yes | — | Canonical terms |
| `label` | string | no | filename stem | Human-readable label |
| `description` | string | no | — | Shown to LLM to guide decisions |
| `growth_policy` | string | no | `"human"` | `auto`, `human`, `llm`, or callable |
| `fuzzy_match` | boolean | no | `true` | Enable fuzzy matching |
| `case_sensitive` | boolean | no | `false` | Case-sensitive matching |
| `capture_ideal` | boolean | no | `false` | Ask LLM for unconstrained answer |
| `persist` | boolean | no | `false` | Save back to file after runs |
| `denied` | list[string] | no | — | Explicitly excluded terms |
| `pending` | list | no | — | Queued suggestions (managed by runner/CLI) |

---

## Standalone usage

`apply_vocab` can be used without the pipeline runner:

```python
from pyconveyor.vocab import Vocabulary, apply_vocab

vocab = Vocabulary(known={"Escherichia coli", "Bacillus subtilis"})
stored, novel, matched, suggestion = apply_vocab("E. coli", vocab, "organism")
# stored="Escherichia coli", novel=None, matched=True, suggestion=None
```
