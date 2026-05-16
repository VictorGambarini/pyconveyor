"""Report generation for BenchmarkSummary — self-contained HTML with no external
CSS/JS dependencies (Chart.js is loaded from CDN with SRI; Mermaid is loaded
via ESM import which does not support SRI)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .benchmark import BenchmarkSummary
from .graph import generate_mermaid

# Sections available in a report, in display order.
ALL_SECTIONS = [
    "overall_summary",
    "per_step_accuracy",
    "pipeline_comparison",
    "mermaid_graph",
    "plots",
    "per_case_breakdown",
    "attempt_logs",
]

DEFAULT_SECTIONS = [s for s in ALL_SECTIONS if s != "attempt_logs"]


def generate_report(
    summary: BenchmarkSummary,
    output: str | Path,
    sections: list[str] | None = None,
    title: str = "Pipeline Benchmark Report",
    pdf: bool = False,
) -> None:
    """Generate an HTML benchmark report (and optionally a PDF).

    Args:
        summary: Result from :meth:`BenchmarkRunner.run`.
        output: Path for the HTML output file.
        sections: Which sections to include.  Defaults to all except
            ``"attempt_logs"``.  Pass ``["attempt_logs"]`` to add it, or a
            full list to restrict.  Available sections:
            ``overall_summary``, ``per_step_accuracy``,
            ``pipeline_comparison``, ``mermaid_graph``, ``plots``,
            ``per_case_breakdown``, ``attempt_logs``.
        title: Report title shown in the HTML ``<title>`` and ``<h1>``.
        pdf: Also write a PDF alongside the HTML file (requires WeasyPrint).
    """
    active = sections if sections is not None else DEFAULT_SECTIONS
    html_str = _render_html(summary, title=title, sections=active)
    out = Path(output)
    out.write_text(html_str, encoding="utf-8")

    if pdf:
        _write_pdf(html_str, out.with_suffix(".pdf"))


# ── HTML rendering ─────────────────────────────────────────────────────────────


def _render_html(
    summary: BenchmarkSummary,
    title: str,
    sections: list[str],
) -> str:
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body_parts: list[str] = []
    section_set = set(sections)
    multi = len(summary.pipelines) > 1

    # Stats bar always rendered (replaces the old Overall Summary card).
    body_parts.append(_stats_bar(summary))

    # Sidebar content: build a ToC as we go.
    toc_items: list[str] = []

    def _add_section(sec_id: str, label: str, html_content: str) -> str:
        if not html_content:
            return ""
        toc_items.append(
            f'<li><a href="#{sec_id}" class="toc-link">{_esc(label)}</a></li>'
        )
        return f'<section id="{sec_id}" class="section">{html_content}</section>'

    # Per-case breakdown first (failures surfaced immediately).
    if "per_case_breakdown" in section_set:
        body_parts.append(
            _add_section("per_case_breakdown", "Case Results", _section_case_cards(summary))
        )

    if "per_step_accuracy" in section_set and any(
        pr.step_mean_accuracy for pr in summary.pipelines
    ):
        body_parts.append(
            _add_section("per_step_accuracy", "Per-Step Accuracy", _section_per_step_accuracy(summary))
        )

    if "pipeline_comparison" in section_set and multi:
        body_parts.append(
            _add_section("pipeline_comparison", "Pipeline Comparison", _section_pipeline_comparison(summary))
        )

    if "mermaid_graph" in section_set:
        body_parts.append(
            _add_section("mermaid_graph", "Pipeline Graph", _section_mermaid_graph(summary))
        )

    if "plots" in section_set:
        body_parts.append(
            _add_section("plots", "Accuracy Plots", _section_plots(summary))
        )

    if "attempt_logs" in section_set:
        body_parts.append(
            _add_section("attempt_logs", "Attempt Logs", _section_attempt_logs(summary))
        )

    side_nav = ""
    if toc_items:
        side_nav = f'<nav class="toc-nav" aria-label="Table of Contents"><ul>{"".join(toc_items)}</ul></nav>'

    body = "\n".join(filter(None, body_parts))

    return _HTML_SHELL.format(
        title=_esc(title),
        timestamp=timestamp,
        side_nav=side_nav,
        body=body,
        chart_js=_chart_js(summary),
    )


# ── Stats bar (replaces old Overall Summary card) ──────────────────────────────


def _stats_bar(summary: BenchmarkSummary) -> str:
    total_cases = sum(len(pr.cases) for pr in summary.pipelines)
    threshold = summary.pass_threshold
    pass_cases = sum(
        sum(1 for c in pr.cases if c.status == "ok" and c.overall_score >= threshold)
        for pr in summary.pipelines
    )
    fail_cases = total_cases - pass_cases
    pipeline_count = len(summary.pipelines)

    pipeline_names = ", ".join(Path(pr.pipeline_path).name for pr in summary.pipelines)
    overall_pct = round(
        sum(pr.overall_mean_accuracy for pr in summary.pipelines) / pipeline_count * 100
    ) if pipeline_count > 0 else 0

    status_label = "pass" if fail_cases == 0 else "fail"
    status_text = "All passing" if fail_cases == 0 else f"{fail_cases} failed"

    return (
        f'<section id="overall_summary" class="stats-bar">'
        f'<div class="stats-bar-inner">'
        f'<div class="stats-left">'
        f'<span class="stats-pipelines">{_esc(pipeline_names)}</span>'
        f'</div>'
        f'<div class="stats-right">'
        f'<span class="stat-badge">{total_cases} cases</span>'
        f'<span class="stat-badge">{pass_cases} pass</span>'
        f'{_stat("stat-badge stat-err", str(fail_cases) + " fail") if fail_cases else ""}'
        f'<span class="stat-badge">{overall_pct}% accuracy</span>'
        f'<span class="stat-badge stat-{status_label}">{status_text}</span>'
        f'</div>'
        f"</div></section>"
    )


def _stat(cls: str, text: str) -> str:
    return f'<span class="{cls}">{text}</span>'


# ── Section renderers ──────────────────────────────────────────────────────────


def _section_per_step_accuracy(summary: BenchmarkSummary) -> str:
    step_names: list[str] = []
    seen: set[str] = set()
    for pr in summary.pipelines:
        for s in pr.step_mean_accuracy:
            if s not in seen:
                step_names.append(s)
                seen.add(s)

    if not step_names:
        return ""

    header_cols = "<th>Step</th>"
    for pr in summary.pipelines:
        label = Path(pr.pipeline_path).name
        header_cols += f"<th>{_esc(label)}</th>"
    if len(summary.pipelines) == 2:
        header_cols += "<th>&#916;</th>"

    rows = []
    for step in step_names:
        row = f"<td><code>{_esc(step)}</code></td>"
        means: list[float] = []
        for pr in summary.pipelines:
            mean = pr.step_mean_accuracy.get(step)
            if mean is None:
                row += '<td class="muted">—</td>'
            else:
                means.append(mean)
                row += f"<td>{_score_badge(mean)}</td>"
        if len(summary.pipelines) == 2 and len(means) == 2:
            delta = means[1] - means[0]
            row += f"<td>{_delta_badge(delta)}</td>"
        rows.append(f"<tr>{row}</tr>")

    return f"""<div class="table-responsive">
<table class="table">
  <thead><tr>{header_cols}</tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table></div>"""


def _section_pipeline_comparison(summary: BenchmarkSummary) -> str:
    pipelines = summary.pipelines
    if len(pipelines) < 2:
        return ""

    all_steps: list[str] = []
    seen: set[str] = set()
    for pr in pipelines:
        for s in pr.step_mean_accuracy:
            if s not in seen:
                all_steps.append(s)
                seen.add(s)

    if not all_steps:
        return ""

    labels = [Path(pr.pipeline_path).name for pr in pipelines]
    base = pipelines[0]

    rows = []
    for step in all_steps:
        base_mean = base.step_mean_accuracy.get(step)
        row = f"<td><code>{_esc(step)}</code></td>"
        row += f"<td>{_score_badge(base_mean) if base_mean is not None else '—'}</td>"
        for pr in pipelines[1:]:
            mean = pr.step_mean_accuracy.get(step)
            if mean is None or base_mean is None:
                row += "<td>—</td><td>—</td>"
            else:
                delta = mean - base_mean
                row += f"<td>{_score_badge(mean)}</td><td>{_delta_badge(delta)}</td>"
        rows.append(f"<tr>{row}</tr>")

    header = f"<th>Step</th><th>{_esc(labels[0])}</th>"
    for lbl in labels[1:]:
        header += f"<th>{_esc(lbl)}</th><th>&#916; vs baseline</th>"

    return f"""<p class="text-muted small">Baseline: <code>{_esc(labels[0])}</code></p>
<div class="table-responsive">
<table class="table">
  <thead><tr>{header}</tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table></div>"""


def _section_mermaid_graph(summary: BenchmarkSummary) -> str:
    diagrams: list[str] = []
    for pr in summary.pipelines:
        label = Path(pr.pipeline_path).name
        try:
            diagram = generate_mermaid(pr.pipeline_path, step_scores=pr.step_mean_accuracy)
        except Exception:
            diagrams.append(
                f'<p class="text-err">Could not generate graph for {_esc(label)}</p>'
            )
            continue
        diagrams.append(
            f'<h6 class="graph-label"><code>{_esc(label)}</code></h6>'
            f'<div class="mermaid">{diagram}</div>'
        )

    if not diagrams:
        return '<p class="muted">No pipeline graphs available.</p>'
    return "\n".join(diagrams)


def _section_plots(summary: BenchmarkSummary) -> str:
    if not summary.pipelines:
        return ""
    multi = len(summary.pipelines) > 1
    charts = '<canvas id="chart-step-accuracy" class="chart"></canvas>'
    if multi:
        charts += '<canvas id="chart-delta" class="chart"></canvas>'
    return charts


# ── Case cards (replaces old monolithic per-case table) ────────────────────────


def _section_case_cards(summary: BenchmarkSummary) -> str:
    parts: list[str] = []
    threshold = summary.pass_threshold
    for pi, pr in enumerate(summary.pipelines):
        label = Path(pr.pipeline_path).name
        if len(summary.pipelines) > 1:
            parts.append(
                f'<h3 class="pipeline-label"><code>{_esc(label)}</code></h3>'
            )

        # Split into failed and passed based on score vs threshold.
        # Cases with execution errors always count as failed.
        failed = [
            c for c in pr.cases
            if c.status == "error" or c.overall_score < threshold
        ]
        passed = [
            c for c in pr.cases
            if c.status == "ok" and c.overall_score >= threshold
        ]

        if not pr.cases:
            parts.append(
                '<div class="empty-state">No benchmark cases found for this pipeline.</div>'
            )
            continue

        if failed:
            for c in failed:
                parts.append(_case_card(c, pi, threshold, auto_expand=True))
        if passed:
            for c in passed:
                parts.append(_case_card(c, pi, threshold, auto_expand=False))

        if not failed:
            parts.append(
                '<div class="empty-state empty-pass">All cases passed.</div>'
            )

    if not any(pr.cases for pr in summary.pipelines):
        return '<div class="empty-state">No benchmark results to display.</div>'

    return "\n".join(parts)


def _case_card(c: Any, pipeline_index: int, threshold: float, auto_expand: bool = False) -> str:
    """Render a single benchmark case as a collapsible card."""
    case_id = _css_safe(f"case-{pipeline_index}-{c.case_name}")
    is_pass = c.status == "ok" and c.overall_score >= threshold
    status_cls = "case-pass" if is_pass else "case-fail"
    status_label = "pass" if is_pass else "fail"
    expanded = "expanded" if auto_expand else ""

    # ── Step score summary (missing / ignored steps) ──
    score_rows: list[str] = []
    for step_name, ss in c.step_scores.items():
        if ss.status == "missing":
            score_rows.append(
                f'<tr><td><code>{_esc(step_name)}</code></td>'
                f'<td colspan="2"><span class="badge badge-warn">missing</span></td></tr>'
            )
        elif ss.status == "ignored":
            score_rows.append(
                f'<tr><td><code>{_esc(step_name)}</code></td>'
                f'<td colspan="2"><span class="badge badge-muted">ignored</span></td></tr>'
            )
        else:
            score_rows.append(
                f'<tr><td><code>{_esc(step_name)}</code></td>'
                f'<td>{_score_badge(ss.score)}</td>'
                f'<td class="muted small">({ss.status})</td>'
                f'</tr>'
            )

    score_table = ""
    if score_rows:
        score_table = (
            f'<details class="score-details">'
            f'<summary class="score-summary">Benchmark scores ({len(score_rows)} step{"s" if len(score_rows) != 1 else ""})</summary>'
            f'<table class="table table-sm" style="margin-top:6px">'
            f'<thead><tr><th>Step</th><th>Score</th><th></th></tr></thead>'
            f'<tbody>{"".join(score_rows)}</tbody></table>'
            f'</details>'
        )

    # ── Interactive comparison block ──
    comp_block = _render_comparison_block(c, case_id)

    error_section = ""
    if c.error:
        error_section = (
            f'<div class="error-block">'
            f'<strong>Error:</strong> {_esc(c.error)}'
            f"</div>"
        )

    return (
        f'<div id="{case_id}" class="case-card {status_cls} {expanded}">'
        f'<button class="case-header" aria-expanded="{"true" if auto_expand else "false"}" '
        f'aria-controls="{case_id}-body" onclick="toggleCase(this)">'
        f'<span class="case-title">'
        f'<span class="case-status-dot" aria-label="{status_label}"></span>'
        f'{_esc(c.case_name)}'
        f'</span>'
        f'<span class="case-score">{_score_badge(c.overall_score)}</span>'
        f'<svg class="case-chevron" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">'
        f'<path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>'
        f"</svg>"
        f"</button>"
        f'<div id="{case_id}-body" class="case-body">'
        f'{error_section}'
        f'{comp_block}'
        f'{score_table}'
        f"</div></div>"
    )


def _section_attempt_logs(summary: BenchmarkSummary) -> str:
    rows: list[str] = []
    for pr in summary.pipelines:
        pipeline_label = Path(pr.pipeline_path).name
        for case in pr.cases:
            for log in case.attempt_logs:
                tokens = log.tokens or {}
                rows.append(
                    f"<tr>"
                    f"<td><code>{_esc(pipeline_label)}</code></td>"
                    f"<td>{_esc(case.case_name)}</td>"
                    f"<td>{_esc(log.step)}</td>"
                    f"<td>{log.attempt}</td>"
                    f"<td>{_status_badge(log.status)}</td>"
                    f"<td>{tokens.get('prompt_tokens', '—')}</td>"
                    f"<td>{tokens.get('completion_tokens', '—')}</td>"
                    f"<td>{log.elapsed_seconds:.2f}s</td>"
                    f"</tr>"
                )

    if not rows:
        return '<p class="muted">No attempt logs recorded.</p>'

    return (
        '<div class="table-responsive"><table class="table">'
        "<thead><tr>"
        "<th>Pipeline</th><th>Case</th><th>Step</th><th>#</th>"
        "<th>Status</th><th>Prompt tokens</th><th>Completion tokens</th>"
        "<th>Elapsed</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


# ── Chart.js data ──────────────────────────────────────────────────────────────

_PALETTE = [
    "#2563eb",  # accent blue
    "#16a34a",  # pass green
    "#dc2626",  # fail red
    "#d97706",  # warn amber
    "#6b7280",  # muted grey
]


def _chart_js(summary: BenchmarkSummary) -> str:
    step_names: list[str] = []
    seen: set[str] = set()
    for pr in summary.pipelines:
        for s in pr.step_mean_accuracy:
            if s not in seen:
                step_names.append(s)
                seen.add(s)

    if not step_names:
        return ""

    datasets: list[dict[str, Any]] = []
    for i, pr in enumerate(summary.pipelines):
        label = Path(pr.pipeline_path).name
        data = [round(pr.step_mean_accuracy.get(s, 0.0) * 100, 1) for s in step_names]
        datasets.append({
            "label": label,
            "data": data,
            "backgroundColor": _PALETTE[i % len(_PALETTE)],
        })

    chart_data = json.dumps({"labels": step_names, "datasets": datasets})
    chart_opts = json.dumps({
        "responsive": True,
        "maintainAspectRatio": False,
        "plugins": {"legend": {"position": "top"}},
        "scales": {
            "y": {
                "min": 0,
                "max": 100,
                "title": {"display": True, "text": "Accuracy (%)"},
            }
        },
    })

    js = f"""
var mainEl = document.getElementById('chart-step-accuracy');
if (mainEl) {{
  new Chart(mainEl, {{
    type: 'bar',
    data: {chart_data},
    options: {chart_opts}
  }});
}}"""

    if len(summary.pipelines) == 2:
        base = summary.pipelines[0]
        comp = summary.pipelines[1]
        delta_data = [
            round((comp.step_mean_accuracy.get(s, 0.0) - base.step_mean_accuracy.get(s, 0.0)) * 100, 1)
            for s in step_names
        ]
        colors = [
            "#16a34a" if d >= 0 else "#dc2626"
            for d in delta_data
        ]
        delta_chart = json.dumps({
            "labels": step_names,
            "datasets": [{
                "label": "Accuracy delta (%)",
                "data": delta_data,
                "backgroundColor": colors,
            }],
        })
        delta_opts = json.dumps({
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {
                "legend": {"position": "top"},
                "title": {
                    "display": True,
                    "text": f"Δ {Path(comp.pipeline_path).name} vs {Path(base.pipeline_path).name}",
                },
            },
            "scales": {"y": {"title": {"display": True, "text": "Δ Accuracy (%)"}}},
        })
        js += f"""
var deltaEl = document.getElementById('chart-delta');
if (deltaEl) {{
  new Chart(deltaEl, {{
    type: 'bar',
    data: {delta_chart},
    options: {delta_opts}
  }});
}}"""

    return js


# ── HTML helpers ───────────────────────────────────────────────────────────────


def _score_badge(score: float | None) -> str:
    if score is None:
        return "—"
    pct = f"{score:.0%}"
    if score >= 0.9:
        cls = "score score-pass"
    elif score >= 0.6:
        cls = "score score-warn"
    else:
        cls = "score score-fail"
    return f'<span class="{cls}">{pct}</span>'


def _delta_badge(delta: float) -> str:
    sign = "+" if delta >= 0 else ""
    cls = "delta-pos" if delta >= 0 else "delta-neg"
    return f'<span class="{cls}">{sign}{delta:.0%}</span>'


def _status_badge(status: str) -> str:
    mapping = {
        "success": "badge badge-pass",
        "parse_error": "badge badge-warn",
        "schema_error": "badge badge-warn",
    }
    cls = mapping.get(status, "badge badge-muted")
    return f'<span class="{cls}">{_esc(status)}</span>'


def _pct(val: float) -> str:
    return f"{val:.0%}"


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _repr(val: Any) -> str:
    if val is None:
        return "—"
    return _esc(repr(val))


def _flatten_leaves(val: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Recursively flatten a nested dict/list to ``(dotted-path, leaf-value)`` pairs.

    Dicts are traversed by key name; lists are indexed as ``[0]``, ``[1]``, …
    Scalars become leaf entries.  Empty containers at *prefix* are emitted as
    ``(prefix, None)`` so the path is always visible in the comparison table.
    """
    if isinstance(val, dict):
        if not val:
            return [(prefix, None)] if prefix else []
        result: list[tuple[str, Any]] = []
        for k, v in val.items():
            child = f"{prefix}.{k}" if prefix else str(k)
            result.extend(_flatten_leaves(v, child))
        return result
    if isinstance(val, list):
        if not val:
            return [(prefix, None)] if prefix else []
        result = []
        for i, v in enumerate(val):
            child = f"{prefix}[{i}]"
            result.extend(_flatten_leaves(v, child))
        return result
    return [(prefix, val)] if prefix else []


def _to_serialisable(val: Any) -> Any:
    """Convert a leaf value to a JSON-serialisable scalar."""
    if val is None or isinstance(val, (bool, int, float, str)):
        return val
    return str(val)


def _build_comp_data(
    c: Any,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Pre-flatten all step outputs and gold expectations into comparison datasets.

    Returns:
        data:    ``{dataset_key: {flat_path: leaf_value, ...}, ...}``
        options: ordered list of ``{key, label}`` dicts for the UI dropdowns.
    """
    data: dict[str, dict[str, Any]] = {}
    options: list[dict[str, str]] = []

    # Gold (expected from expected.yaml) — one entry per scored step
    for step_name in sorted(c.expecteds.keys()):
        expected_val = c.expecteds[step_name]
        key = f"gold__{step_name}"
        flat = _flatten_leaves(expected_val)
        data[key] = {path: _to_serialisable(v) for path, v in flat}
        options.append({"key": key, "label": f"Gold: {step_name}"})

    # All step actual outputs (includes unscored pipeline steps)
    for step_name in sorted(c.actuals.keys()):
        actual_val = c.actuals[step_name]
        if actual_val is None:
            continue
        key = f"step__{step_name}"
        flat = _flatten_leaves(actual_val)
        data[key] = {path: _to_serialisable(v) for path, v in flat}
        options.append({"key": key, "label": f"Step: {step_name}"})

    return data, options


def _render_comparison_block(c: Any, case_id: str) -> str:
    """Render the interactive field-comparison table for *c*.

    Embeds all step data as inline JSON; the table is built and updated by
    client-side JS (``compInit`` / ``compUpdate`` / ``compSort`` / ``compFilter``).
    """
    data, options = _build_comp_data(c)
    if not data or len(options) < 1:
        return ""

    # Sensible defaults: Gold on the left (if available), last scored step on right
    gold_keys = [o["key"] for o in options if o["key"].startswith("gold__")]
    step_keys = [o["key"] for o in options if o["key"].startswith("step__")]

    left_default = gold_keys[0] if gold_keys else options[0]["key"]
    # For the right, prefer a step__ key that matches the gold step name
    right_default = options[-1]["key"]
    if gold_keys and step_keys:
        gold_step = gold_keys[0].removeprefix("gold__")
        matching = [k for k in step_keys if k == f"step__{gold_step}"]
        right_default = matching[0] if matching else step_keys[-1]

    def _opts_html(selected: str) -> str:
        return "".join(
            f'<option value="{_esc(o["key"])}"'
            f'{" selected" if o["key"] == selected else ""}>'
            f"{_esc(o['label'])}</option>"
            for o in options
        )

    cid = _css_safe(case_id)
    json_data = json.dumps(data, ensure_ascii=False)

    return (
        f'<div class="comp-block">'
        f'<script type="application/json" id="comp-json-{cid}">{json_data}</script>'
        f'<div class="comp-controls">'
        f'<label class="comp-sel-label">Left'
        f'<select class="comp-sel comp-left" data-case="{cid}" '
        f'onchange="compUpdate(\'{cid}\')">{_opts_html(left_default)}</select></label>'
        f'<span class="comp-vs">vs</span>'
        f'<label class="comp-sel-label">Right'
        f'<select class="comp-sel comp-right" data-case="{cid}" '
        f'onchange="compUpdate(\'{cid}\')">{_opts_html(right_default)}</select></label>'
        f'<label class="comp-sel-label comp-filter-label">Show'
        f'<select class="comp-filter" data-case="{cid}" '
        f'onchange="compFilter(\'{cid}\')">'
        f'<option value="all">All fields</option>'
        f'<option value="diff">Differences only</option>'
        f'<option value="fail">Failures only</option>'
        f'</select></label>'
        f'</div>'
        f'<table class="comp-table" id="comp-table-{cid}">'
        f'<thead><tr>'
        f'<th class="comp-th sortable" onclick="compSort(\'{cid}\',0)">Field</th>'
        f'<th class="comp-th sortable" onclick="compSort(\'{cid}\',1)">Left</th>'
        f'<th class="comp-th sortable" onclick="compSort(\'{cid}\',2)">Right</th>'
        f'<th class="comp-th sortable" onclick="compSort(\'{cid}\',3)">Status</th>'
        f'</tr></thead>'
        f'<tbody id="comp-tbody-{cid}"></tbody>'
        f'</table>'
        f'<script>compInit("{cid}","{_esc(left_default)}","{_esc(right_default)}");</script>'
        f'</div>'
    )


def _css_safe(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", str(name))



# ── PDF export ─────────────────────────────────────────────────────────────────


def _write_pdf(html_str: str, pdf_path: Path) -> None:
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "PDF export requires WeasyPrint.  Install it with:\n"
            "  pip install weasyprint"
        ) from exc
    HTML(string=html_str).write_pdf(str(pdf_path))


# ── HTML shell ─────────────────────────────────────────────────────────────────

_HTML_SHELL = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    /* ── Custom Properties ── */
    :root {{
      --surface: #ffffff;
      --bg: #f5f5f7;
      --text: #1a1a1a;
      --text-secondary: #4b5563;
      --text-muted: #9ca3af;
      --accent: #2563eb;
      --accent-bg: #eff6ff;
      --pass: #16a34a;
      --pass-bg: #f0fdf4;
      --pass-border: #bbf7d0;
      --warn: #d97706;
      --warn-bg: #fffbeb;
      --warn-border: #fde68a;
      --fail: #dc2626;
      --fail-bg: #fef2f2;
      --fail-border: #fecaca;
      --border: #e5e7eb;
      --border-light: #f3f4f6;
      --radius: 6px;
      --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      --font-mono: 'SF Mono', 'Cascadia Code', 'Consolas', 'Liberation Mono', 'Menlo', monospace;
      --sidebar-w: 240px;
    }}

    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: var(--font);
      font-size: 15px;
      line-height: 1.5;
      color: var(--text);
      background: var(--bg);
      -webkit-font-smoothing: antialiased;
    }}

    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    /* ── Layout ── */
    .app {{ display: flex; min-height: 100vh; }}

    .sidebar {{
      width: var(--sidebar-w);
      flex-shrink: 0;
      background: var(--surface);
      border-right: 1px solid var(--border);
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
      padding: 1.5rem;
    }}

    .main {{
      flex: 1;
      min-width: 0;
      max-width: 1200px;
      padding: 1.25rem 2rem 3rem;
    }}

    /* ── Sidebar / ToC ── */
    .sidebar-title {{
      font-size: 13px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 0.75rem;
    }}

    .toc-nav ul {{
      list-style: none;
      padding: 0;
    }}

    .toc-link {{
      display: block;
      padding: 0.35rem 0.5rem;
      border-radius: 4px;
      font-size: 13px;
      color: var(--text-secondary);
      transition: background 0.1s;
    }}

    .toc-link:hover {{
      background: var(--border-light);
      text-decoration: none;
    }}

    /* ── Stats Bar ── */
    .stats-bar {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 0.75rem 1.25rem;
      margin-bottom: 1.5rem;
      position: sticky;
      top: 0;
      z-index: 10;
    }}

    .stats-bar-inner {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 0.5rem 1rem;
    }}

    .stats-left {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }}

    .stats-pipelines {{
      font-weight: 600;
      font-size: 14px;
    }}

    .stats-right {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}

    .stat-badge {{
      display: inline-block;
      padding: 0.15rem 0.6rem;
      border-radius: 99px;
      font-size: 12px;
      font-weight: 500;
      background: var(--border-light);
      color: var(--text-secondary);
    }}

    .stat-err {{ background: var(--fail-bg); color: var(--fail); }}

    .stat-pass {{
      background: var(--pass-bg);
      color: var(--pass);
      font-weight: 600;
    }}

    .stat-fail {{
      background: var(--fail-bg);
      color: var(--fail);
      font-weight: 600;
    }}

    /* ── Sections ── */
    .section {{
      margin-bottom: 2rem;
    }}

    .section > h2 {{
      font-size: 18px;
      font-weight: 600;
      margin-bottom: 0.75rem;
      padding-bottom: 0.5rem;
      border-bottom: 1px solid var(--border);
    }}

    /* ── Tables ── */
    .table-responsive {{
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface);
    }}

    .table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}

    .table thead {{
      background: #f9fafb;
      border-bottom: 2px solid var(--border);
    }}

    .table th {{
      padding: 0.5rem 0.75rem;
      text-align: left;
      font-weight: 600;
      font-size: 12px;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.03em;
      white-space: nowrap;
    }}

    .table td {{
      padding: 0.4rem 0.75rem;
      border-top: 1px solid var(--border-light);
      vertical-align: top;
    }}

    .table tr:first-child td {{ border-top: none; }}

    .table-sm th, .table-sm td {{ padding: 0.3rem 0.5rem; font-size: 12px; }}

    .table-nested {{
      margin: 0.25rem 0;
      border: 1px solid var(--border);
      border-radius: 4px;
      font-size: 12px;
    }}

    /* ── Case Cards ── */
    .case-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      margin-bottom: 0.5rem;
      overflow: hidden;
    }}

    .case-card.case-fail {{
      border-left: 3px solid var(--fail);
    }}

    .case-card.case-pass {{
      border-left: 3px solid var(--pass);
    }}

    .case-header {{
      display: flex;
      align-items: center;
      width: 100%;
      padding: 0.6rem 1rem;
      background: none;
      border: none;
      cursor: pointer;
      font-family: var(--font);
      font-size: 14px;
      text-align: left;
      gap: 0.75rem;
      transition: background 0.1s;
    }}

    .case-header:hover {{ background: #f9fafb; }}

    .case-header:focus-visible {{
      outline: 2px solid var(--accent);
      outline-offset: -2px;
    }}

    .case-title {{
      flex: 1;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-weight: 500;
    }}

    .case-status-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }}

    .case-fail .case-status-dot {{ background: var(--fail); }}
    .case-pass .case-status-dot {{ background: var(--pass); }}

    .case-score {{
      font-size: 13px;
    }}

    .case-chevron {{
      color: var(--text-muted);
      transition: transform 0.15s;
      flex-shrink: 0;
    }}

    .case-card.expanded .case-chevron {{
      transform: rotate(180deg);
    }}

    .case-body {{
      display: none;
      padding: 0 1rem 1rem;
      border-top: 1px solid var(--border-light);
    }}

    .case-card.expanded .case-body {{
      display: block;
    }}

    /* ── Scores & Badges ── */
    .score {{
      display: inline-block;
      padding: 0.1rem 0.45rem;
      border-radius: 99px;
      font-size: 12px;
      font-weight: 600;
      font-family: var(--font-mono);
    }}

    .score-pass {{ background: var(--pass-bg); color: var(--pass); }}
    .score-warn {{ background: var(--warn-bg); color: var(--warn); }}
    .score-fail {{ background: var(--fail-bg); color: var(--fail); }}

    .badge {{
      display: inline-block;
      padding: 0.1rem 0.5rem;
      border-radius: 99px;
      font-size: 11px;
      font-weight: 600;
    }}

    .badge-pass {{ background: var(--pass-bg); color: var(--pass); }}
    .badge-warn {{ background: var(--warn-bg); color: var(--warn); }}
    .badge-muted {{ background: var(--border-light); color: var(--text-muted); }}

    .delta-pos {{ color: var(--pass); font-weight: 600; font-family: var(--font-mono); font-size: 13px; }}
    .delta-neg {{ color: var(--fail); font-weight: 600; font-family: var(--font-mono); font-size: 13px; }}

    /* ── Benchmark score details ── */
    .score-details {{ margin-top: 0.5rem; margin-bottom: 0.25rem; }}
    .score-summary {{
      cursor: pointer;
      font-size: 12px;
      color: var(--text-muted);
      padding: 0.2rem 0.4rem;
      list-style: none;
      display: inline-flex;
      align-items: center;
      gap: 0.25rem;
    }}
    .score-summary::-webkit-details-marker {{ display: none; }}
    .score-summary::before {{ content: "▶"; font-size: 9px; }}
    details[open] .score-summary::before {{ content: "▼"; }}

    /* ── Comparison block ── */
    .comp-block {{ margin: 0.75rem 0; }}

    .comp-controls {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: wrap;
      margin-bottom: 0.5rem;
      padding: 0.4rem 0.6rem;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 6px;
    }}
    .comp-sel-label {{
      display: flex;
      align-items: center;
      gap: 0.35rem;
      font-size: 12px;
      color: var(--text-secondary);
      font-weight: 500;
    }}
    .comp-filter-label {{ margin-left: auto; }}
    .comp-sel, .comp-filter {{
      font-size: 12px;
      padding: 0.2rem 0.4rem;
      border: 1px solid var(--border);
      border-radius: 4px;
      background: var(--bg);
      color: var(--fg);
      cursor: pointer;
    }}
    .comp-vs {{
      font-size: 11px;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}

    /* ── Comparison table ── */
    .comp-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      table-layout: fixed;
    }}
    .comp-table col.col-field  {{ width: 28%; }}
    .comp-table col.col-left   {{ width: 28%; }}
    .comp-table col.col-right  {{ width: 28%; }}
    .comp-table col.col-status {{ width: 16%; }}

    .comp-th {{
      padding: 0.35rem 0.6rem;
      text-align: left;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-secondary);
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      border-top: 1px solid var(--border);
      white-space: nowrap;
    }}
    .comp-th.sortable {{ cursor: pointer; user-select: none; }}
    .comp-th.sortable:hover {{ background: var(--border-light); }}
    .comp-th .sort-icon {{ font-size: 9px; margin-left: 3px; opacity: 0.5; }}
    .comp-th.sort-asc .sort-icon::after  {{ content: "▲"; opacity: 1; }}
    .comp-th.sort-desc .sort-icon::after {{ content: "▼"; opacity: 1; }}

    .comp-td {{
      padding: 0.3rem 0.6rem;
      border-bottom: 1px solid var(--border-light);
      vertical-align: top;
      word-break: break-word;
      font-family: var(--font-mono);
    }}
    .comp-td.col-field  {{ font-size: 11px; color: var(--text-secondary); font-family: var(--font-mono); }}
    .comp-td.col-status {{ font-family: var(--font-sans); font-size: 12px; font-weight: 600; }}

    /* Row status tints */
    .comp-row-match  {{ background: rgba(34,197,94,0.06); }}
    .comp-row-close  {{ background: rgba(251,191,36,0.08); }}
    .comp-row-fail   {{ background: rgba(239,68,68,0.08); }}
    .comp-row-left   {{ background: rgba(249,115,22,0.07); }}
    .comp-row-right   {{ background: rgba(59,130,246,0.07); }}
    .comp-row-ignored {{ background: var(--surface); color: var(--text-muted); }}

    /* Group separator / header rows */
    .comp-group-sep {{ height: 4px; background: transparent; }}
    .comp-group-header {{ background: var(--bg); border-top: 2px solid var(--border); }}
    .comp-group-label {{
      padding: 4px 8px 3px;
      font-size: 11px;
      font-weight: 700;
      color: var(--text-secondary);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}

    /* Status icon colours */
    .comp-icon-match   {{ color: var(--pass); }}
    .comp-icon-close   {{ color: var(--warn); }}
    .comp-icon-fail    {{ color: var(--fail); }}
    .comp-icon-left    {{ color: #f97316; }}
    .comp-icon-right   {{ color: #3b82f6; }}
    .comp-icon-ignored {{ color: var(--text-muted); }}

    /* Long value expand */
    .comp-val-short  {{ display: inline; }}
    .comp-val-full   {{ display: none; }}
    .comp-val-short.expanded .comp-val-text {{ display: none; }}
    .comp-val-short.expanded .comp-val-full {{ display: inline; }}
    .comp-val-btn {{
      background: none; border: none;
      color: var(--accent); cursor: pointer;
      font-size: 10px; padding: 0 2px;
      font-family: var(--font-mono);
    }}
    .comp-val-btn:hover {{ text-decoration: underline; }}


    /* ── Mermaid ── */
    .mermaid {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1rem;
      overflow-x: auto;
    }}

    .graph-label {{
      font-size: 13px;
      font-weight: 600;
      margin: 0.75rem 0 0.5rem;
      color: var(--text-secondary);
    }}

    /* ── Charts ── */
    .chart {{
      width: 100%;
      height: 300px;
      margin-bottom: 1rem;
    }}

    /* ── Error block ── */
    .error-block {{
      background: var(--fail-bg);
      border: 1px solid var(--fail-border);
      border-radius: var(--radius);
      padding: 0.75rem 1rem;
      margin: 0.75rem 0;
      font-size: 13px;
      color: var(--fail);
    }}

    /* ── Empty states ── */
    .empty-state {{
      text-align: center;
      padding: 2rem 1rem;
      color: var(--text-muted);
      font-size: 14px;
    }}

    .empty-pass {{
      color: var(--pass);
      font-weight: 500;
    }}

    /* ── Pipeline label ── */
    .pipeline-label {{
      font-size: 16px;
      font-weight: 600;
      margin: 1rem 0 0.5rem;
      padding-top: 0.5rem;
      border-top: 1px solid var(--border);
    }}

    .pipeline-label:first-child {{
      border-top: none;
      margin-top: 0;
      padding-top: 0;
    }}

    /* ── Utilities ── */
    .muted {{ color: var(--text-muted); }}
    .small {{ font-size: 12px; }}
    .text-err {{ color: var(--fail); }}

    code {{
      font-family: var(--font-mono);
      font-size: 0.9em;
      background: #f3f4f6;
      padding: 0.1em 0.3em;
      border-radius: 3px;
    }}

    /* ── Responsive ── */
    @media (max-width: 768px) {{
      .app {{ flex-direction: column; }}

      .sidebar {{
        width: 100%;
        height: auto;
        position: static;
        border-right: none;
        border-bottom: 1px solid var(--border);
        padding: 0.75rem 1rem;
      }}

      .toc-nav ul {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.25rem;
      }}

      .toc-link {{
        padding: 0.2rem 0.5rem;
        font-size: 12px;
      }}

      .main {{
        padding: 1rem;
      }}

      .stats-bar-inner {{
        flex-direction: column;
        align-items: flex-start;
      }}

    }}

    /* ── Print ── */
    @media print {{
      .sidebar {{
        display: none;
      }}

      .stats-bar {{
        position: static;
        break-inside: avoid;
      }}

      .case-card {{
        break-inside: avoid;
        border: 1px solid #ddd;
      }}

      .case-body {{
        display: block !important;
      }}

      .case-header {{
        cursor: default;
      }}

      .case-chevron {{
        display: none;
      }}

      body {{
        font-size: 12px;
        background: white;
      }}

      .main {{
        max-width: none;
        padding: 0;
      }}

    }}
  </style>
</head>
<body>
<div class="app">
  <aside class="sidebar" aria-label="Table of Contents">
    <div class="sidebar-title">Sections</div>
    {side_nav}
  </aside>
  <main class="main">
    <h1 class="mb-1" style="font-size:22px;font-weight:700;margin-bottom:0.15rem;">{title}</h1>
    <p class="small muted" style="margin-bottom:1.25rem;">Generated: {timestamp}</p>
    {body}
  </main>
</div>
<script>
  function toggleCase(btn) {{
    var card = btn.parentElement;
    var expanded = btn.getAttribute('aria-expanded') === 'true';
    btn.setAttribute('aria-expanded', !expanded);
    card.classList.toggle('expanded');
  }}

  /* ── Field-comparison table ── */
  var _compState = {{}};

  function escHtml(s) {{
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }}

  function compFmt(v) {{
    if (v === null || v === undefined) return '<span style="color:var(--text-muted)">—</span>';
    var s = String(v);
    if (s.length <= 80) return '<code>' + escHtml(s) + '</code>';
    var short = escHtml(s.slice(0,80));
    var full  = escHtml(s);
    return '<span class="comp-val-short">'
      + '<code class="comp-val-text">' + short + '…</code>'
      + '<button class="comp-val-btn" onclick="this.closest(\\'.comp-val-short\\').classList.toggle(\\'expanded\\')">[+]</button>'
      + '<code class="comp-val-full" hidden>' + full + '</code>'
      + '</span>';
  }}

  function compGroup(path) {{
    // Extract top-level group from path: e.g. entries[0].name → entries[0]
    var m = path.match(/^([^.]+(?:\\[\\d+\\])?)/);
    return m ? m[1] : path;
  }}

  function compCompare(a, b) {{
    // $ignore sentinel: field is explicitly excluded from scoring
    if (a === '$ignore' || b === '$ignore') return 'ignored';
    if (a === undefined) return 'right';
    if (b === undefined) return 'left';
    if (a === b) return 'match';
    // numeric within 5%
    var na = parseFloat(a), nb = parseFloat(b);
    if (!isNaN(na) && !isNaN(nb) && na !== 0) {{
      if (Math.abs(na - nb) / Math.abs(na) <= 0.05) return 'close';
    }}
    return 'fail';
  }}

  function compStatusIcon(status) {{
    var map = {{
      match:   ['comp-icon-match',   '✓ match'],
      close:   ['comp-icon-close',   '~ close'],
      fail:    ['comp-icon-fail',    '✗ fail'],
      left:    ['comp-icon-left',    '← left only'],
      right:   ['comp-icon-right',   '→ right only'],
      ignored: ['comp-icon-ignored', '— ignored'],
    }};
    var pair = map[status] || ['', status];
    return '<span class="' + pair[0] + '">' + escHtml(pair[1]) + '</span>';
  }}

  function compRowClass(status) {{
    return {{ match:'comp-row-match', close:'comp-row-close', fail:'comp-row-fail',
              left:'comp-row-left', right:'comp-row-right',
              ignored:'comp-row-ignored' }}[status] || '';
  }}

  function compRender(cid, leftKey, rightKey) {{
    var jsonEl = document.getElementById('comp-json-' + cid);
    if (!jsonEl) return;
    var data = JSON.parse(jsonEl.textContent);
    var left  = data[leftKey]  || {{}};
    var right = data[rightKey] || {{}};

    // Union of all paths
    var pathSet = {{}};
    Object.keys(left).forEach(function(k)  {{ pathSet[k] = 1; }});
    Object.keys(right).forEach(function(k) {{ pathSet[k] = 1; }});
    var paths = Object.keys(pathSet).sort();

    var st = _compState[cid] || {{}};
    var filter = st.filter || 'all';
    var sortCol = st.sortCol !== undefined ? st.sortCol : -1;
    var sortDir = st.sortDir || 'asc';

    // Build rows data
    var rows = paths.map(function(p) {{
      var lv = left.hasOwnProperty(p)  ? left[p]  : undefined;
      var rv = right.hasOwnProperty(p) ? right[p] : undefined;
      var status = compCompare(lv, rv);
      return {{ path: p, left: lv, right: rv, status: status }};
    }});

    // Filter
    if (filter === 'diff') {{
      rows = rows.filter(function(r) {{ return r.status !== 'match' && r.status !== 'ignored'; }});
    }} else if (filter === 'fail') {{
      rows = rows.filter(function(r) {{ return r.status === 'fail' || r.status === 'left' || r.status === 'right'; }});
    }}

    // Sort
    if (sortCol >= 0) {{
      var getKey = [
        function(r) {{ return r.path; }},
        function(r) {{ return r.left === undefined ? '' : String(r.left); }},
        function(r) {{ return r.right === undefined ? '' : String(r.right); }},
        function(r) {{ return r.status; }},
      ][sortCol];
      rows.sort(function(a, b) {{
        var ak = getKey(a), bk = getKey(b);
        if (ak < bk) return sortDir === 'asc' ? -1 : 1;
        if (ak > bk) return sortDir === 'asc' ?  1 : -1;
        return 0;
      }});
    }}

    // Build HTML rows, inserting group-separator headers between list-index groups
    // Only when sorting by field (col 0) or default (no sort), so groups are contiguous
    var addGroupHeaders = (sortCol === -1 || sortCol === 0);
    var lastGroup = null;
    var htmlParts = [];
    rows.forEach(function(r) {{
      if (addGroupHeaders) {{
        var grp = compGroup(r.path);
        if (grp !== lastGroup) {{
          if (lastGroup !== null) {{
            htmlParts.push('<tr class="comp-group-sep"><td colspan="4"></td></tr>');
          }}
          htmlParts.push(
            '<tr class="comp-group-header">'
            + '<td colspan="4" class="comp-group-label"><code>' + escHtml(grp) + '</code></td>'
            + '</tr>'
          );
          lastGroup = grp;
        }}
      }}
      htmlParts.push(
        '<tr class="' + compRowClass(r.status) + '">'
        + '<td class="comp-td col-field"><code>' + escHtml(r.path) + '</code></td>'
        + '<td class="comp-td col-left">'  + compFmt(r.left)  + '</td>'
        + '<td class="comp-td col-right">' + compFmt(r.right) + '</td>'
        + '<td class="comp-td col-status">' + compStatusIcon(r.status) + '</td>'
        + '</tr>'
      );
    }});
    var html = htmlParts.join('');

    var tbody = document.getElementById('comp-tbody-' + cid);
    if (tbody) tbody.innerHTML = html || '<tr><td colspan="4" style="padding:0.5rem;color:var(--text-muted)">No fields to display.</td></tr>';

    // Update sort icons
    var table = document.getElementById('comp-table-' + cid);
    if (table) {{
      var ths = table.querySelectorAll('.comp-th');
      ths.forEach(function(th, i) {{
        th.classList.remove('sort-asc', 'sort-desc');
        var icon = th.querySelector('.sort-icon');
        if (!icon) {{ icon = document.createElement('span'); icon.className = 'sort-icon'; th.appendChild(icon); }}
        icon.textContent = '';
        if (i === sortCol) {{
          th.classList.add('sort-' + sortDir);
        }}
      }});
    }}
  }}

  function compInit(cid, leftKey, rightKey) {{
    _compState[cid] = {{ filter: 'all', sortCol: -1, sortDir: 'asc' }};
    compRender(cid, leftKey, rightKey);
  }}

  function compUpdate(cid) {{
    var block = document.querySelector('#comp-table-' + cid)
                  ? document.getElementById('comp-table-' + cid).closest('.comp-block')
                  : null;
    if (!block) return;
    var leftSel  = block.querySelector('.comp-left');
    var rightSel = block.querySelector('.comp-right');
    if (!leftSel || !rightSel) return;
    compRender(cid, leftSel.value, rightSel.value);
  }}

  function compSort(cid, colIdx) {{
    var st = _compState[cid] || {{}};
    if (st.sortCol === colIdx) {{
      if (st.sortDir === 'asc')  st.sortDir = 'desc';
      else if (st.sortDir === 'desc') {{ st.sortCol = -1; st.sortDir = 'asc'; }}
    }} else {{
      st.sortCol = colIdx; st.sortDir = 'asc';
    }}
    _compState[cid] = st;
    compUpdate(cid);
  }}

  function compFilter(cid) {{
    var block = document.querySelector('#comp-table-' + cid)
                  ? document.getElementById('comp-table-' + cid).closest('.comp-block')
                  : null;
    if (!block) return;
    var filterSel = block.querySelector('.comp-filter');
    if (!filterSel) return;
    _compState[cid] = _compState[cid] || {{}};
    _compState[cid].filter = filterSel.value;
    compUpdate(cid);
  }}
</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"
  integrity="sha384-NrKB+u6Ts6AtkIhwPixiKTzgSKNblyhlk0Sohlgar9UHUBzai/sgnNNWWd291xqt"
  crossorigin="anonymous"></script>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({{ startOnLoad: false, theme: 'default' }});
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', function() {{ mermaid.run(); }});
  }} else {{
    mermaid.run();
  }}
</script>
<script>
{chart_js}
</script>
</body>
</html>"""
