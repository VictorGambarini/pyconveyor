"""Report generation for BenchmarkSummary — self-contained HTML with no external
CSS/JS dependencies (Chart.js is loaded from CDN with SRI; Mermaid is loaded
via ESM import which does not support SRI)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

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

    # Collect step names in order.
    all_steps: list[str] = []
    seen_steps: set[str] = set()
    for s in c.step_scores:
        if s not in seen_steps:
            all_steps.append(s)
            seen_steps.add(s)

    # Separate steps: those with multiple FieldScores (get a field table section)
    # vs those with 0–1 FieldScores (go in the compact step summary table).
    simple_steps: list[str] = []
    detail_steps: list[str] = []
    for step_name in all_steps:
        ss = c.step_scores.get(step_name)
        if ss is not None and ss.field_scores and len(ss.field_scores) > 1:
            detail_steps.append(step_name)
        else:
            simple_steps.append(step_name)

    # ── Compact step summary table (missing/ignored/single-FieldScore steps) ──
    simple_rows: list[str] = []
    for step_name in simple_steps:
        ss = c.step_scores.get(step_name)
        if ss is None:
            continue
        if ss.status == "missing":
            simple_rows.append(
                f'<tr><td><code>{_esc(step_name)}</code></td>'
                f'<td colspan="3"><span class="badge badge-warn">missing</span></td></tr>'
            )
        elif ss.status == "ignored":
            simple_rows.append(
                f'<tr><td><code>{_esc(step_name)}</code></td>'
                f'<td colspan="3"><span class="badge badge-muted">ignored</span></td></tr>'
            )
        else:
            exp_val = c.expecteds.get(step_name)
            act_val = _reorder_to_expected(c.actuals.get(step_name), exp_val)
            simple_rows.append(
                f'<tr><td><code>{_esc(step_name)}</code></td>'
                f'<td>{_score_badge(ss.score)}</td>'
                f'<td class="val-cell">{_fmt_value(exp_val)}</td>'
                f'<td class="val-cell">{_fmt_value(act_val)}</td>'
                f'</tr>'
            )

    simple_table = ""
    if simple_rows:
        simple_table = (
            f'<table class="table table-sm">'
            f'<thead><tr>'
            f'<th>Step</th><th>Score</th><th>Expected</th><th>Actual</th>'
            f'</tr></thead>'
            f'<tbody>{"".join(simple_rows)}</tbody></table>'
        )

    # ── Field comparison sections (steps with multiple FieldScores) ──
    detail_sections: list[str] = []
    for step_name in detail_steps:
        ss = c.step_scores.get(step_name)
        if ss is None:
            continue
        field_table = _render_field_table(step_name, ss)
        detail_sections.append(
            f'<div class="step-section">'
            f'<div class="step-section-header">'
            f'<code>{_esc(step_name)}</code>'
            f'<span class="step-section-score">{_score_badge(ss.score)}</span>'
            f'</div>'
            f'{field_table}'
            f'</div>'
        )

    detail_content = "\n".join(detail_sections)

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
        f'{simple_table}'
        f'{detail_content}'
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


def _reorder_to_expected(actual: Any, expected: Any) -> Any:
    """Reorder *actual* dict keys to match *expected*'s insertion order.

    Extra keys in *actual* not present in *expected* are appended at the end.
    Applied recursively to nested dicts.  Non-dict values are returned unchanged.
    """
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return actual
    ordered: dict[str, Any] = {}
    for key in expected:
        if key in actual:
            ordered[key] = _reorder_to_expected(actual[key], expected.get(key))
    for key in actual:
        if key not in expected:
            ordered[key] = actual[key]
    return ordered


def _fmt_value(val: Any, truncate: int = 120) -> str:
    """Format a field value for display in an HTML table cell.

    Scalars are rendered as plain escaped text; dicts and lists are serialised
    as YAML inline (``default_flow_style=True``).  Values longer than *truncate*
    characters are shown truncated with a keyboard-accessible ``[+]`` expand toggle.
    """
    if val is None:
        return '<span class="muted">—</span>'
    if isinstance(val, (dict, list)):
        text = yaml.dump(
            val,
            default_flow_style=True,
            allow_unicode=True,
            Dumper=yaml.SafeDumper,
        ).strip()
    else:
        text = str(val)
    if len(text) > truncate:
        safe = _esc(text[:truncate])
        full = _esc(text)
        return (
            f'<span class="val-short">'
            f'<code class="val-short-text">{safe}…</code>'
            f'<button class="val-expand" aria-label="Show full value" '
            f'onclick="this.closest(\'.val-short\').classList.toggle(\'val-expanded\')">[+]</button>'
            f'<code class="val-full" hidden>{full}</code>'
            f'</span>'
        )
    return f'<code class="mono-cell">{_esc(text)}</code>'


def _match_icon(score: float, status: str) -> str:
    """Return an ARIA-labelled icon span for a field match result."""
    if status == "ignored":
        return '<span aria-label="ignored" class="icon-ignored">—</span>'
    if score >= 1.0:
        return '<span aria-label="pass" class="icon-pass">✓</span>'
    if score <= 0.0:
        return '<span aria-label="fail" class="icon-fail">✗</span>'
    return '<span aria-label="partial" class="icon-warn">~</span>'


def _render_field_table(step_name: str, ss: Any) -> str:
    """Render a structured field comparison table for a step with multiple FieldScores.

    Failing fields are surfaced first (always visible).  Passing and ignored
    fields are wrapped in a ``<details>`` collapse to reduce visual noise.
    """
    if not ss.field_scores or len(ss.field_scores) <= 1:
        return ""

    fail_rows: list[str] = []
    pass_rows: list[str] = []

    for f in ss.field_scores:
        is_fail = f.score < 1.0 and f.status != "ignored"
        if f.status == "ignored":
            row_cls = "field-row field-ignored"
        elif f.score >= 1.0:
            row_cls = "field-row field-pass"
        elif f.score <= 0.0:
            row_cls = "field-row field-fail"
        else:
            row_cls = "field-row field-warn"

        row = (
            f'<tr class="{row_cls}">'
            f'<td><code class="field-path">{_esc(f.field)}</code></td>'
            f'<td class="val-cell">{_fmt_value(f.expected)}</td>'
            f'<td class="val-cell">{_fmt_value(f.actual)}</td>'
            f'<td class="icon-cell">{_match_icon(f.score, f.status)}</td>'
            f'</tr>'
        )
        if is_fail:
            fail_rows.append(row)
        else:
            pass_rows.append(row)

    thead = (
        '<table class="table table-sm field-table">'
        '<thead><tr>'
        '<th>Field</th><th>Expected</th><th>Actual</th><th></th>'
        '</tr></thead>'
        '<tbody>'
    )
    tfoot = '</tbody></table>'

    fail_body = "".join(fail_rows)
    if pass_rows:
        pass_count = len(pass_rows)
        s_plural = "s" if pass_count != 1 else ""
        pass_body = (
            f'<tr class="pass-collapse-row"><td colspan="4" style="padding:0">'
            f'<details>'
            f'<summary class="pass-summary">'
            f'{pass_count} passing field{s_plural}</summary>'
            f'<table class="table table-sm field-table-inner">'
            f'<tbody>{"".join(pass_rows)}</tbody>'
            f'</table>'
            f'</details>'
            f'</td></tr>'
        )
    else:
        pass_body = ""

    return thead + fail_body + pass_body + tfoot


def _css_safe(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", str(name))


# ── Diff rendering ─────────────────────────────────────────────────────────────
# Removed: _render_step_diff, _build_side_by_side_diff, _build_unified_diff,
# _word_diff_side_by_side.  The structured field comparison table (_render_field_table)
# supersedes the YAML text diff entirely.


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

    /* ── Field rows ── */
    .field-detail td {{ padding: 0; }}

    .field-row.field-pass {{ background: var(--pass-bg); }}
    .field-row.field-warn {{ background: var(--warn-bg); }}
    .field-row.field-fail {{ background: var(--fail-bg); }}
    .field-row.field-ignored {{ background: var(--border-light); color: var(--text-muted); }}

    .field-table {{ margin: 0.5rem 0; }}
    .field-table-inner {{ margin: 0; }}
    .field-path {{ font-size: 11px; }}
    .val-cell {{ font-family: var(--font-mono); font-size: 12px; max-width: 320px; word-break: break-word; }}
    .icon-cell {{ width: 28px; text-align: center; }}
    .icon-pass {{ color: var(--pass); font-weight: 700; }}
    .icon-fail {{ color: var(--fail); font-weight: 700; }}
    .icon-warn {{ color: var(--warn); font-weight: 700; }}
    .icon-ignored {{ color: var(--text-muted); }}
    .mono-cell {{ font-size: 12px; }}

    /* ── Step section (steps with full field detail) ── */
    .step-section {{ margin-top: 0.75rem; }}
    .step-section-header {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.25rem 0;
      font-size: 13px;
      font-weight: 600;
      color: var(--text-secondary);
      border-bottom: 1px solid var(--border-light);
      margin-bottom: 0.25rem;
    }}
    .step-section-score {{ margin-left: auto; }}

    /* ── Pass-collapse (passing fields hidden behind <details>) ── */
    .pass-collapse-row td {{ padding: 0 !important; border-top: 1px solid var(--border-light); }}
    .pass-summary {{
      cursor: pointer;
      padding: 0.3rem 0.75rem;
      font-size: 12px;
      color: var(--text-muted);
      background: var(--border-light);
      list-style: none;
      display: flex;
      align-items: center;
      gap: 0.25rem;
    }}
    .pass-summary::-webkit-details-marker {{ display: none; }}
    .pass-summary::before {{ content: "▶"; font-size: 10px; }}
    details[open] .pass-summary::before {{ content: "▼"; }}

    /* ── Value expand toggle ── */
    .val-short {{ display: inline; }}
    .val-full {{ display: none; }}
    .val-short.val-expanded .val-short-text {{ display: none; }}
    .val-short.val-expanded .val-full {{ display: inline; }}
    .val-expand {{
      background: none;
      border: none;
      color: var(--accent);
      cursor: pointer;
      font-size: 11px;
      padding: 0 2px;
      font-family: var(--font-mono);
    }}
    .val-expand:hover {{ text-decoration: underline; }}

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
</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"
  integrity="sha384-NrKB+u6Ts6AtkIhwPixiKTzgSKNblyhlk0Sohlgar9UHUBzai/sgnNNWWd291xqt"
  crossorigin="anonymous"></script>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
</script>
<script>
{chart_js}
</script>
</body>
</html>"""
