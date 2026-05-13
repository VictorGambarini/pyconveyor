# Benchmarking

Benchmarking lets you measure how well a pipeline performs against a set of documents where you already know the correct answers — your **golden standard**. You get per-step accuracy scores, so you can see exactly which steps help, hurt, or are neutral, and compare multiple pipeline variants side by side.

---

## The idea in one picture

```
benchmarks/
├── case_paper_001/
│   ├── input.yaml      ← what you pass to the pipeline (or input.json)
│   └── expected.yaml   ← the correct output you expect (or expected.json)
├── case_paper_002/
│   ├── input.yaml
│   └── expected.yaml
└── ...
```

For each case the runner calls your pipeline, compares actual vs expected for every step, computes a score (0.0–1.0), and aggregates across all cases.

---

## Quick start

### 1. Create the benchmark directory

```bash
mkdir -p benchmarks/case_001
```

### 2. Write an input file

```yaml
# benchmarks/case_001/input.yaml
paper: "Smith et al. (2024) demonstrate that CRISPR-Cas9 gene editing achieves 94% efficiency in primary human T cells. This breakthrough was published in Nature Biotechnology (doi:10.1038/s41586-024-01234)."
```

For large inputs, use `$file` references (resolved relative to the case directory):

```yaml
doi: "10.1234/example"
paper_markdown:
  $file: paper.md
```

### 3. Write the expected output

The keys in `expected.yaml` are step names. The values are the fields you want to check.

```yaml
# benchmarks/case_001/expected.yaml
extract:
  title: "CRISPR-Cas9 Gene Editing in Primary Human T Cells"
  authors: ["J. Smith", "A. Chen", "M. Patel"]
  doi: "10.1038/s41586-024-01234"
  publication_year: 2024
```

You don't have to cover all steps — only the ones you want to measure.

### 4. Run the benchmark

```bash
pyconveyor benchmark benchmarks/ --pipeline pipeline.yaml --report report.html
```

Console output:

```
Pipeline: pipeline.yaml
  Step 'extract'   accuracy: 87.5%   pass rate: 62.5% (threshold: 100%)
  Overall          accuracy: 87.5%

Report written to: report.html
```

### 5. Open the report

```bash
open report.html   # macOS
xdg-open report.html  # Linux
```

> **Screenshot placeholder:** the HTML report overview table showing per-step accuracy and overall score.

---

## Directory layout

```
benchmarks/
└── <case_name>/        ← any directory name; used as the case label in the report
  ├── input.yaml | input.yml | input.json         ← required (exactly one)
  └── expected.yaml | expected.yml | expected.json ← required (exactly one)
```

Cases are discovered by walking `benchmark_dir` and finding every directory that contains exactly one input file and one expected file.
If a case has multiple formats for the same role (for example both `input.json` and `input.yaml`), benchmarking fails fast with a configuration error.

---

## The `expected.yaml` format

```json
{
  "<step_name>": {
    "<field>": <value>,
    "<field>": <value>
  },
  "<another_step>": "scalar value",
  "<optional_step>": "$ignore"
}
```

- **Pydantic model steps** — provide a dict of fields. Each field is scored independently and the step score is the mean of all field scores. Nested dicts are recursively scored field-by-field.
- **Transform / io steps** — provide the exact scalar, dict, or list value the step should return.
- **Omitting a step** — steps not listed in `expected.*` are not scored (they don't affect accuracy).
- **`$ignore` sentinel** — mark any field, list element, or entire step as excluded from scoring (see [Ignoring fields](#ignoring-fields)).

### Example: classification step

```json
{
  "classify": {
    "field": "molecular biology",
    "confidence": 0.95
  }
}
```

`confidence` is a float — by default scored with exact equality. Use a custom comparator for fuzzy numeric matching (see [Custom comparators](#custom-comparators)).

---

## Scoring

All containers (dicts, lists) are scored recursively. Dict fields produce per-field scores; list elements are matched element-by-element.

### How a field is scored

By default, each field uses **exact equality**: score is `1.0` if actual == expected, `0.0` otherwise.

### How a step is scored

For dict outputs, the step score is the **mean of all non-ignored field scores**:

```
step_score = mean([field_1_score, field_2_score, ..., field_n_score])
```

For scalar (non-dict, non-list) outputs, the step is scored directly as 1.0 or 0.0.

Steps where every field is `$ignore` (or the step itself is `"$ignore"`) get status `"ignored"` and are excluded from the overall case score.

### How a pipeline run is scored

The overall score for a case is the **mean across all scored steps** (ignored and missing steps excluded).

### Pass rate

A case **passes** when its overall score meets a threshold (default: `1.0`, i.e. perfect). You can lower this:

```bash
pyconveyor benchmark benchmarks/ --pipeline pipeline.yaml --pass-threshold 0.8
```

The report shows both mean accuracy and pass rate. Mean accuracy tells you how good you are on average; pass rate tells you how often you're good enough.

---
## Ignoring fields

Use the `$ignore` sentinel to exclude fields, list elements, or entire steps from scoring. Excluded positions are **removed from the denominator** — they don't inflate or deflate your scores.

### Ignoring individual fields

```json
{
  "extract": {
    "title": "Gene Therapy Advances",
    "notes": "$ignore"
  }
}
```

The `notes` field is not scored. The step score is based on `title` alone.

### Ignoring an entire step

```json
{
  "extract": {
    "title": "Gene Therapy Advances"
  },
  "summary": "$ignore"
}
```

The `summary` step is excluded from the overall case score entirely. Same effect as omitting it from `expected.json`, but makes your intent explicit.

### Ignoring nested fields

Comparison recurses into nested dicts, so `$ignore` works at any depth:

```json
{
  "extract": {
    "metadata": {
      "source": "PubMed",
      "internal_id": "$ignore"
    },
    "title": "Gene Therapy Advances"
  }
}
```

### Ignoring list elements

`$ignore` works inside lists as a wildcard element — it consumes one actual element without scoring it:

```json
{
  "extract": {
    "authors": ["Ada Lovelace", "$ignore", "Grace Hopper"]
  }
}
```

The `$ignore` says "I expect a third author but I don't care who." If the actual output has exactly three authors, the extra one is consumed by the wildcard and the score stays high. If the actual output has only two, the wildcard is unsatisfied and the denominator includes it.

### Ignored status in reports

Ignored steps and fields appear with a neutral "ignored" label in the HTML report's per-case breakdown, so you can always see what was excluded.

---
## List matching

By default, scalar lists use **set-based overlap** (order doesn't matter). Dict lists use **greedy best-match pairing** (order doesn't matter). For positional matching, use the `$ordered` directive.

### Set-based overlap (default for scalar lists)

```json
{
  "extract": {
    "keywords": ["CRISPR", "gene therapy"]
  }
}
```

If the actual output is `["gene therapy", "CRISPR", "ethics"]`, the two expected keywords are found in the actual set → score `1.0`. Duplicates are handled with `Counter` semantics — expecting `["a", "a"]` and getting `["a", "b"]` scores `0.5`.

### $ordered — positional matching

When order matters, wrap the expected list with `{"$ordered": [...]}`:

```json
{
  "extract": {
    "steps": {"$ordered": ["isolate DNA", "apply CRISPR", "sequence"]}
  }
}
```

Each position is compared independently. If the actual output is `["apply CRISPR", "isolate DNA", "sequence"]`, the score is `0.33` (only position 2 matches). With default set-overlap the same pair would score `1.0`.

### Best-match dict lists (default for dict lists)

When matching a list of objects (e.g. extracted authors), each expected dict is greedily paired with the best-scoring unmatched actual dict:

```json
{
  "extract": {
    "authors": [
      {"name": "Ada Lovelace", "affiliation": "Cambridge"},
      {"name": "Grace Hopper", "affiliation": "Harvard"}
    ]
  }
}
```

If the actual output lists the authors in a different order, scoring is still `1.0` because each expected dict finds its best match in the actual list. Partial field matches within each dict produce fractional scores.

---

## Custom comparators

For cases where exact equality is too strict, pass a comparators dict via the Python API:

```python
from pyconveyor import BenchmarkRunner, generate_report

def case_insensitive(actual, expected):
    return 1.0 if str(actual).lower() == str(expected).lower() else 0.0

def within_10_percent(actual, expected):
    if expected == 0:
        return 1.0 if actual == 0 else 0.0
    return 1.0 if abs(actual - expected) / abs(expected) <= 0.1 else 0.0

runner = BenchmarkRunner(
    benchmark_dir="benchmarks/",
    pipelines=["pipeline.yaml"],
    comparators={
        "extract.vendor": case_insensitive,      # step_name.field_name
        "extract.amount": within_10_percent,
    },
)

summary = runner.run()
generate_report(summary, "report.html")
```

Custom comparators receive `(actual_value, expected_value)` and must return a float in `[0.0, 1.0]`.

---

## Comparing multiple pipelines

Run the same cases through multiple pipelines and compare scores side by side.

### CLI

```bash
pyconveyor benchmark benchmarks/ \
  --pipeline pipeline_v1.yaml \
  --pipeline pipeline_v2.yaml \
  --pipeline pipeline_v3.yaml \
  --report comparison.html
```

> **Screenshot placeholder:** the pipeline comparison delta table in the HTML report, showing which pipeline wins per step.

### Python API

```python
from pyconveyor import BenchmarkRunner, generate_report

runner = BenchmarkRunner(
    benchmark_dir="benchmarks/",
    pipelines=["pipeline_v1.yaml", "pipeline_v2.yaml", "pipeline_v3.yaml"],
)

summary = runner.run()
generate_report(summary, "comparison.html")
```

### How comparison works

- **Shared step names** — compared directly with a delta (v2 − v1).
- **Partial overlap** — shared steps are compared; unshared steps shown separately.
- **No shared steps** — only overall accuracy is compared.

---

## The HTML report

The report is a self-contained HTML file (Bootstrap 5, Chart.js, Mermaid.js — all CDN). No server needed, works offline once loaded, can be shared by email or Slack.

### Report sections

| Section | Default | Description |
|---|---|---|
| `overall_summary` | ✓ included | Summary table: accuracy and pass rate per pipeline |
| `per_step_accuracy` | ✓ included | Per-step accuracy table across all cases |
| `pipeline_comparison` | ✓ included | Delta table (only shown when ≥2 pipelines) |
| `mermaid_graph` | ✓ included | Pipeline DAG with accuracy percentages on each node |
| `plots` | ✓ included | Bar charts of per-step accuracy per pipeline |
| `per_case_breakdown` | ✓ included | Collapsible table: every case, every step, every field score |
| `attempt_logs` | ✗ excluded | Raw LLM attempt logs — noisy, useful for debugging |

> **Screenshot placeholder:** the Mermaid pipeline graph with accuracy percentages annotated on each step node.

> **Screenshot placeholder:** the per-case breakdown collapsible showing field-level scores.

### Controlling sections

```bash
# Include everything including attempt logs
pyconveyor benchmark benchmarks/ \
  --pipeline pipeline.yaml \
  --sections overall_summary per_step_accuracy pipeline_comparison mermaid_graph plots per_case_breakdown attempt_logs \
  --report full_report.html

# Share a clean summary with your boss (no raw logs, no per-case detail)
pyconveyor benchmark benchmarks/ \
  --pipeline pipeline.yaml \
  --sections overall_summary per_step_accuracy pipeline_comparison plots \
  --report summary_report.html
```

Python API:

```python
generate_report(
    summary,
    "report.html",
    sections=["overall_summary", "per_step_accuracy", "plots"],
    title="Invoice Extraction — Sprint 3 Review",
)
```

### PDF export

Install WeasyPrint, then pass `--pdf`:

```bash
pip install weasyprint
pyconveyor benchmark benchmarks/ --pipeline pipeline.yaml --report report.html --pdf
```

This writes both `report.html` and `report.pdf` to the same directory.

Python API:

```python
generate_report(summary, "report.html", pdf=True)
```

---

## Full CLI reference

```bash
pyconveyor benchmark <benchmark_dir> [options]
```

| Argument / Option | Default | Description |
|---|---|---|
| `benchmark_dir` | — | Directory containing benchmark cases |
| `--pipeline`, `-p` | — | Pipeline YAML file(s). Repeat for multiple |
| `--report`, `-r` | `benchmark_report.html` | Output HTML report path |
| `--pdf` | off | Also export a PDF alongside the HTML |
| `--pass-threshold` | `1.0` | Minimum score to count as a passing case |
| `--sections` | all except `attempt_logs` | Space-separated list of sections to include |
| `--title` | `Pipeline Benchmark Report` | Report title |

---

## Python API

### `BenchmarkRunner`

```python
from pyconveyor import BenchmarkRunner

runner = BenchmarkRunner(
    benchmark_dir="benchmarks/",       # str or Path
    pipelines=["pipeline.yaml"],       # list of str or Path
    comparators={},                    # optional custom field comparators
    pass_threshold=1.0,                # float in [0, 1]
    schemas={"step": MyModel},         # optional Pydantic model injection
)

summary = runner.run()  # → BenchmarkSummary
```

### `BenchmarkSummary`

```python
summary.pipelines       # list[PipelineBenchmarkResult]
summary.case_names      # list[str]
summary.pass_threshold  # float
```

### `PipelineBenchmarkResult`

```python
result = summary.pipelines[0]

result.pipeline_path           # str
result.overall_mean_accuracy   # float — mean across all cases
result.overall_pass_rate       # float — fraction of passing cases
result.step_mean_accuracy      # dict[str, float] — per step
result.step_pass_rate          # dict[str, float] — per step
result.cases                   # list[CaseResult]
```

### `CaseResult`

```python
case = result.cases[0]

case.case_name         # str
case.status            # "success" | "error"
case.overall_score     # float
case.elapsed_seconds   # float
case.step_scores       # list[StepScore]
case.error             # Exception | None
```

### `StepScore`

```python
step = case.step_scores[0]

step.step_name     # str
step.score         # float
step.field_scores  # list[FieldScore]
```

### `FieldScore`

```python
field = step.field_scores[0]

field.field     # str
field.actual    # Any
field.expected  # Any
field.score     # float
```

### `generate_report`

```python
from pyconveyor import generate_report

generate_report(
    summary,                    # BenchmarkSummary
    output="report.html",       # str or Path
    sections=None,              # list[str] | None → use DEFAULT_SECTIONS
    title="Benchmark Report",   # str
    pdf=False,                  # bool — also write a PDF
)
```

---

## End-to-end example

This example benchmarks two pipeline versions against 10 labelled papers.

### Project layout

```
paper_project/
├── pipeline_v1.yaml
├── pipeline_v2.yaml
├── schemas.py
├── prompts/
│   └── extract.j2
└── benchmarks/
    ├── case_001/
    │   ├── input.json
    │   └── expected.json
    ├── case_002/
    │   ├── input.json
    │   └── expected.json
    └── ... (8 more cases)
```

### `benchmarks/case_001/input.json`

```json
{
  "paper": "Smith et al. (2024) demonstrate that CRISPR-Cas9 gene editing achieves 94% efficiency in primary human T cells."
}
```

### `benchmarks/case_001/expected.json`

```json
{
  "extract": {
    "title": "CRISPR-Cas9 Gene Editing in Primary Human T Cells",
    "authors": ["J. Smith", "A. Chen", "M. Patel"],
    "doi": "10.1038/s41586-024-01234",
    "publication_year": 2024
  }
}
```

### Run the comparison

```bash
pyconveyor benchmark benchmarks/ \
  --pipeline pipeline_v1.yaml \
  --pipeline pipeline_v2.yaml \
  --pass-threshold 0.75 \
  --title "Invoice extraction: v1 vs v2" \
  --report comparison.html

open comparison.html
```

### Or from Python

```python
from pyconveyor import BenchmarkRunner, generate_report

def fuzzy_amount(actual, expected):
    """Accept if within 1% of expected."""
    if expected == 0:
        return 1.0 if actual == 0 else 0.0
    return 1.0 if abs(actual - expected) / abs(expected) <= 0.01 else 0.0

runner = BenchmarkRunner(
    benchmark_dir="benchmarks/",
    pipelines=["pipeline_v1.yaml", "pipeline_v2.yaml"],
    comparators={"extract.amount": fuzzy_amount},
    pass_threshold=0.75,
)

summary = runner.run()

for pipeline_result in summary.pipelines:
    print(f"\n{pipeline_result.pipeline_path}")
    for step, score in pipeline_result.step_mean_accuracy.items():
        print(f"  {step}: {score:.1%}")
    print(f"  Overall: {pipeline_result.overall_mean_accuracy:.1%}")

generate_report(
    summary,
    "comparison.html",
    title="Paper extraction: v1 vs v2",
    sections=["overall_summary", "per_step_accuracy", "pipeline_comparison", "plots"],
)
```

---

## Tips

**Start with one case.** Get a single `input.json` + `expected.json` pair working before you collect 100 cases.

**Name cases clearly.** The case directory name is the label in the report. Use names like `case_paper_simple`, `case_paper_review`, `case_paper_multiauthor` — not `case_001`.

**Cover edge cases.** The most valuable cases are the ones your pipeline currently gets wrong. Add a case for each known failure mode.

**Pin your model temperature.** Use `temperature: 0` and `seed: 42` in your YAML when benchmarking. Deterministic runs make scores stable across runs.

**Use `--sections` to share.** When sending results to a non-technical stakeholder, use `--sections overall_summary plots` to keep the report clean and readable.
