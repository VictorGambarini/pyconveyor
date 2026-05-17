# TODOs

## Benchmark report — comparison UX (§22)

### TODO-1: `_reorder_to_expected` helper

**What:** Add `_reorder_to_expected(actual: Any, expected: Any) -> Any` to `report.py`. Recursively reorders actual dict keys to match expected's insertion order; keys present in actual but not in expected are collected separately (shown in a collapsed "Extra fields" section).

**Why:** The current YAML text diff shows key-order differences as line changes, flooding the diff with noise unrelated to real value mismatches. Reordering makes the comparison visually trivial.

**Pros:** Eliminates the single biggest source of false-noise in the diff; zero runtime cost.

**Cons:** The "extra fields" section adds a small amount of HTML per step.

**Context:** Used in `_render_field_table()` before building rows. Needed by TODO-2, TODO-3, and TODO-4.

**Depends on:** None — standalone pure function.

---

### TODO-2: Replace `_repr()` with `_fmt_value()` in field table cells

**What:** Implement `_fmt_value(val, truncate=120)` in `report.py`:
- Scalar values → plain HTML-escaped string
- Dict/list values → `yaml.dump(val, default_flow_style=True)`, stripped, monospace
- Values longer than 120 chars → truncated with `[+]` expand/collapse toggle (keyboard-accessible `<button>`)

**Why:** `repr()` produces unreadable Python-style strings for dicts (`{'key': 'value'}`) and lists. YAML inline format (`{key: value}`) is what users wrote in their expected files, so it reads naturally.

**Pros:** Values look like what the user typed in expected.yaml; sequences readable without Python noise.

**Cons:** YAML dump for deeply nested values can still be verbose — truncation mitigates this.

**Context:** Replaces all `_repr(f.actual)` and `_repr(f.expected)` calls in the field table. Sequence truncation threshold is 120 chars (chosen to fit a screen at 13px monospace).

**Depends on:** TODO-1 (actual is reordered first, then formatted).

---

### TODO-3: Best-match entry pairing display for list-of-dict fields

**What:** When a `FieldScore` covers a list-of-dict field (e.g. `apply_evidence.entries`), the benchmark scorer uses best-match assignment. Expose this pairing in the report:

```
Entry 1  [score: 85%]
  Field         Expected       Actual        ✓
  organism_name Clono. rosea   Clono. rosea  ✓
  plastic       PCL            PET           ✗
  ...
Entry 2  [score: 100%]
  ...
Unmatched actual entries (1)   [collapsed]
```

**Why:** Without this, the reader has no way to know which actual entry the scorer matched to which expected entry. They must mentally reconstruct the pairing from field paths, which is error-prone.

**Pros:** Makes best-match pairing explicit; surplus actual entries visible but not noisy.

**Cons:** Requires `BenchmarkRunner` to expose the pairing assignments in `FieldScore`, or the display reconstructs it from the field path naming convention.

**Context:** Check whether `FieldScore.field` paths already encode the matched index (e.g. `entries[0].organism_name` where `[0]` is the matched actual index). If yes, the display can reconstruct the grouping from paths alone without touching `benchmark.py`.

**Depends on:** TODO-1, TODO-2.

---

### TODO-4: Failures-first field table with collapsed passing rows

**What:** Within each step's field comparison, render failing `FieldScore` entries first (rows with `score < 1.0` and `status != "ignored"`), then wrap all passing + ignored rows in a `<details><summary>N passing fields</summary>…</details>` toggle.

**Why:** Cases with 20+ fields (like `apply_evidence`) currently force the reader to scroll through 18 passing rows to find the 2 failures. Failures-first puts the problem immediately visible.

**Pros:** Instant failure visibility; passing rows still accessible; no information lost.

**Cons:** Changes row order relative to expected.yaml's field order — some readers may prefer seeing fields in declaration order even when that means scrolling past passes.

**Context:** The `<details>` collapse is the right HTML primitive here (no JS needed). Failed rows stay in expected's field order among themselves.

**Depends on:** TODO-1, TODO-2.

---

### TODO-5: Remove YAML text diff functions

**What:** Delete `_render_step_diff`, `_build_side_by_side_diff`, `_build_unified_diff`, `_word_diff_side_by_side`, and all associated CSS (`.diff-side`, `.diff-unified`, `.diff-header-row`, `.diff-hdr`, `.diff-hunk`, `.diff-del`, `.diff-add`, `.wdiff-del`, `.wdiff-add`, `.diff-section`, `.diff-heading`, `.diff-step-label`, `.diff-collapse`, etc.) from `report.py`.

**Why:** The field table (TODO-1 through TODO-4) supersedes the YAML text diff. Keeping both creates confusion about which is authoritative.

**Pros:** Removes ~200 lines from `report.py`; eliminates the CSS bundle for diff styling; simpler mental model.

**Cons:** Power users who were using the raw diff to inspect non-FieldScore steps lose access. (Mitigation: non-FieldScore steps still show the step-level actual/expected repr in the step table.)

**Context:** The `diff_section` variable in `_case_card` is removed. The `_render_step_diff` call chain is the only caller — safe to delete.

**Depends on:** TODO-1, TODO-2, TODO-3, TODO-4 should land first so the replacement is in place.

---

### TODO-6: ARIA labels on match column icons

**What:** The match column in the field table uses `✓`, `✗`, `~`, `—` symbols. Wrap each in a `<span aria-label="pass">✓</span>` (or fail/partial/ignored). The expand toggle in `_fmt_value` already has `aria-label`.

**Why:** Colour alone (`--pass` green, `--fail` red) is not sufficient for colour-blind users or screen readers. One-line fix.

**Pros:** Correct accessibility practice; required by WCAG 1.4.1 (Use of Color).

**Cons:** Minimal — four small HTML attribute additions.

**Context:** Affects only `_match_icon()` (new helper) or inline in the field row renderer.

**Depends on:** TODO-2 (field table renderer is where icons are emitted).
