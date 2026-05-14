"""Report generation for BenchmarkSummary — HTML (default) and PDF export."""
from __future__ import annotations

import difflib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .benchmark import BenchmarkSummary, PipelineBenchmarkResult
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

# Number of context lines shown around each diff hunk.
_DIFF_CONTEXT_LINES = 3


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
    html = _render_html(summary, title=title, sections=active)
    out = Path(output)
    out.write_text(html, encoding="utf-8")

    if pdf:
        _write_pdf(html, out.with_suffix(".pdf"))


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

    if "overall_summary" in section_set:
        body_parts.append(_section_overall_summary(summary))

    if "per_step_accuracy" in section_set:
        body_parts.append(_section_per_step_accuracy(summary))

    if "pipeline_comparison" in section_set and multi:
        body_parts.append(_section_pipeline_comparison(summary))

    if "mermaid_graph" in section_set:
        body_parts.append(_section_mermaid_graph(summary))

    if "plots" in section_set:
        body_parts.append(_section_plots(summary))

    if "per_case_breakdown" in section_set:
        body_parts.append(_section_per_case_breakdown(summary))

    if "attempt_logs" in section_set:
        body_parts.append(_section_attempt_logs(summary))

    body = "\n".join(body_parts)

    return _HTML_SHELL.format(
        title=_esc(title),
        timestamp=timestamp,
        body=body,
        chart_js=_chart_js(summary),
    )


# ── Section renderers ──────────────────────────────────────────────────────────

def _section_overall_summary(summary: BenchmarkSummary) -> str:
    rows = []
    for pr in summary.pipelines:
        label = Path(pr.pipeline_path).name
        ok = sum(1 for c in pr.cases if c.status == "ok")
        err = sum(1 for c in pr.cases if c.status == "error")
        total = len(pr.cases)
        rows.append(
            f"<tr>"
            f"<td><code>{_esc(label)}</code></td>"
            f"<td>{total}</td>"
            f"<td>{ok}</td>"
            f"<td>{err}</td>"
            f"<td>{_score_badge(pr.overall_mean_accuracy)}</td>"
            f"<td>{_pct(pr.overall_pass_rate)} "
            f"<small class='text-muted'>(≥{summary.pass_threshold:.0%})</small></td>"
            f"</tr>"
        )
    return _card(
        "overall_summary",
        "Overall Summary",
        f"""<table class="table table-bordered table-sm mb-0">
  <thead class="table-light">
    <tr>
      <th>Pipeline</th><th>Cases</th><th>OK</th><th>Errors</th>
      <th>Mean Accuracy</th><th>Pass Rate</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>""",
    )


def _section_per_step_accuracy(summary: BenchmarkSummary) -> str:
    # Collect all step names across all pipelines
    step_names: list[str] = []
    seen: set[str] = set()
    for pr in summary.pipelines:
        for s in pr.step_mean_accuracy:
            if s not in seen:
                step_names.append(s)
                seen.add(s)

    header_cols = "<th>Step</th>"
    for pr in summary.pipelines:
        label = Path(pr.pipeline_path).name
        header_cols += f"<th>{_esc(label)}<br/><small>mean / pass</small></th>"
    if len(summary.pipelines) == 2:
        header_cols += "<th>Delta (mean)</th>"

    rows = []
    for step in step_names:
        row = f"<td><code>{_esc(step)}</code></td>"
        means: list[float] = []
        for pr in summary.pipelines:
            mean = pr.step_mean_accuracy.get(step)
            pass_rate = pr.step_pass_rate.get(step)
            if mean is None:
                row += "<td class='text-muted'>—</td>"
            else:
                means.append(mean)
                row += f"<td>{_score_badge(mean)} / {_pct(pass_rate or 0.0)}</td>"
        if len(summary.pipelines) == 2 and len(means) == 2:
            delta = means[1] - means[0]
            row += f"<td>{_delta_badge(delta)}</td>"
        rows.append(f"<tr>{row}</tr>")

    return _card(
        "per_step_accuracy",
        "Per-Step Accuracy",
        f"""<table class="table table-bordered table-sm mb-0">
  <thead class="table-light"><tr>{header_cols}</tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>""",
    )


def _section_pipeline_comparison(summary: BenchmarkSummary) -> str:
    pipelines = summary.pipelines
    if len(pipelines) < 2:
        return ""
    # Find common steps
    all_steps: list[str] = []
    seen: set[str] = set()
    for pr in pipelines:
        for s in pr.step_mean_accuracy:
            if s not in seen:
                all_steps.append(s)
                seen.add(s)

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
        header += f"<th>{_esc(lbl)}</th><th>Δ vs baseline</th>"

    return _card(
        "pipeline_comparison",
        "Pipeline Comparison",
        f"""<p class="text-muted small">Baseline: <code>{_esc(labels[0])}</code></p>
<table class="table table-bordered table-sm mb-0">
  <thead class="table-light"><tr>{header}</tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>""",
    )


def _section_mermaid_graph(summary: BenchmarkSummary) -> str:
    diagrams: list[str] = []
    for pr in summary.pipelines:
        label = Path(pr.pipeline_path).name
        try:
            diagram = generate_mermaid(pr.pipeline_path, step_scores=pr.step_mean_accuracy)
        except Exception:
            diagrams.append(
                f"<p class='text-danger'>Could not generate graph for {_esc(label)}</p>"
            )
            continue
        diagrams.append(
            f"<h6 class='mt-3'><code>{_esc(label)}</code></h6>"
            f'<div class="mermaid">\n{diagram}</div>'
        )

    return _card("mermaid_graph", "Pipeline Graph", "\n".join(diagrams))


def _section_plots(summary: BenchmarkSummary) -> str:
    multi = len(summary.pipelines) > 1
    charts = '<canvas id="chart-step-accuracy" class="mb-4" style="max-height:350px"></canvas>'
    if multi:
        charts += '<canvas id="chart-delta" class="mb-4" style="max-height:350px"></canvas>'
    return _card("plots", "Accuracy Plots", charts)


def _section_per_case_breakdown(summary: BenchmarkSummary) -> str:
    parts: list[str] = []
    for pr in summary.pipelines:
        label = Path(pr.pipeline_path).name
        parts.append(f"<h6 class='mt-3'><code>{_esc(label)}</code></h6>")
        parts.append(_case_table(pr))
    return _card("per_case_breakdown", "Per-Case Breakdown", "\n".join(parts))


def _case_table(pr: PipelineBenchmarkResult) -> str:
    all_steps: list[str] = []
    seen: set[str] = set()
    for c in pr.cases:
        for s in c.step_scores:
            if s not in seen:
                all_steps.append(s)
                seen.add(s)

    header = "<th>Case</th><th>Status</th><th>Overall</th>"
    for s in all_steps:
        header += f"<th>{_esc(s)}</th>"
    header += "<th>Diff</th>"

    rows: list[str] = []
    for c in pr.cases:
        status_badge = (
            '<span class="badge bg-danger">error</span>'
            if c.status == "error"
            else '<span class="badge bg-success">ok</span>'
        )
        row = (
            f"<td>{_esc(c.case_name)}</td>"
            f"<td>{status_badge}</td>"
            f"<td>{_score_badge(c.overall_score)}</td>"
        )
        for s in all_steps:
            ss = c.step_scores.get(s)
            if ss is None:
                row += "<td class='text-muted'>—</td>"
            elif ss.status == "missing":
                row += "<td><span class='text-warning'>missing</span></td>"
            elif ss.status == "ignored":
                row += "<td><span class='text-muted'>ignored</span></td>"
            else:
                cell = _score_badge(ss.score)
                if ss.field_scores and len(ss.field_scores) > 1:
                    css_id = _css_safe(f"d-{c.case_name}-{s}")
                    detail_rows = "".join(
                        '<tr class="{}"><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                            _field_row_class(f.score, f.status),
                            _esc(f.field),
                            _repr(f.actual),
                            _repr(f.expected),
                            '<span class="text-muted">ignored</span>'
                            if f.status == "ignored"
                            else _score_badge(f.score),
                        )
                        for f in ss.field_scores
                    )
                    detail = (
                        f'<div class="collapse" id="{css_id}">'
                        f'<table class="table table-sm mt-1"><thead><tr>'
                        f"<th>Field</th><th>Actual</th><th>Expected</th><th>Score</th>"
                        f"</tr></thead><tbody>{detail_rows}</tbody></table></div>"
                    )
                    toggle = (
                        f' <a class="text-decoration-none" data-bs-toggle="collapse"'
                        f' href="#{css_id}" title="expand fields">▾</a>'
                    )
                    row += f"<td>{cell}{toggle}{detail}</td>"
                else:
                    row += f"<td>{cell}</td>"

        # Diff link + collapsible diff sections for all steps
        diff_id = _css_safe(f"diff-{c.case_name}")
        diff_parts: list[str] = []
        if c.status == "ok":
            for s in all_steps:
                ss = c.step_scores.get(s)
                if ss is None or ss.status in ("missing", "ignored"):
                    continue
                exp_val = c.expecteds.get(s)
                act_val = c.actuals.get(s)
                if exp_val is not None:
                    diff_parts.append(
                        _render_step_diff(c.case_name, s, exp_val, act_val)
                    )
        diff_toggle = (
            f' <a class="text-decoration-none small" data-bs-toggle="collapse"'
            f' href="#{diff_id}" title="show diff">diff</a>'
        )
        diff_container = (
            f'<div class="collapse" id="{diff_id}">{"".join(diff_parts)}</div>'
        )
        row += f"<td>{diff_toggle}{diff_container}</td>"

        if c.error:
            row += f"<td colspan='99' class='text-danger small'>{_esc(c.error)}</td>"
        rows.append(f"<tr>{row}</tr>")

    return (
        f'<table class="table table-bordered table-sm">'
        f"<thead class='table-light'><tr>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
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
        content = "<p class='text-muted'>No attempt logs recorded.</p>"
    else:
        content = (
            '<table class="table table-bordered table-sm mb-0">'
            "<thead class='table-light'><tr>"
            "<th>Pipeline</th><th>Case</th><th>Step</th><th>#</th>"
            "<th>Status</th><th>Prompt tokens</th><th>Completion tokens</th>"
            "<th>Elapsed</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    return _card("attempt_logs", "Attempt Logs", content)


# ── Chart.js data ──────────────────────────────────────────────────────────────

_PALETTE = [
    "rgba(13,110,253,0.8)",   # Bootstrap blue
    "rgba(25,135,84,0.8)",    # Bootstrap green
    "rgba(220,53,69,0.8)",    # Bootstrap red
    "rgba(255,193,7,0.8)",    # Bootstrap yellow
    "rgba(108,117,125,0.8)",  # Bootstrap grey
]


def _chart_js(summary: BenchmarkSummary) -> str:
    # Collect all step names
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
new Chart(document.getElementById('chart-step-accuracy'), {{
  type: 'bar',
  data: {chart_data},
  options: {chart_opts}
}});"""

    if len(summary.pipelines) == 2:
        base = summary.pipelines[0]
        comp = summary.pipelines[1]
        delta_data = [
            round((comp.step_mean_accuracy.get(s, 0.0) - base.step_mean_accuracy.get(s, 0.0)) * 100, 1)
            for s in step_names
        ]
        colors = [
            "rgba(25,135,84,0.8)" if d >= 0 else "rgba(220,53,69,0.8)"
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

def _card(section_id: str, heading: str, content: str) -> str:
    return (
        f'<section id="{section_id}" class="mb-4">'
        f'<div class="card shadow-sm">'
        f'<div class="card-header fw-semibold">{_esc(heading)}</div>'
        f'<div class="card-body">{content}</div>'
        f"</div></section>"
    )


def _score_badge(score: float) -> str:
    pct = f"{score:.0%}"
    if score >= 0.9:
        cls = "text-success fw-bold"
    elif score >= 0.6:
        cls = "text-warning fw-bold"
    else:
        cls = "text-danger fw-bold"
    return f'<span class="{cls}">{pct}</span>'


def _delta_badge(delta: float) -> str:
    sign = "+" if delta >= 0 else ""
    cls = "text-success" if delta >= 0 else "text-danger"
    return f'<span class="{cls} fw-bold">{sign}{delta:.0%}</span>'


def _status_badge(status: str) -> str:
    mapping = {
        "success": "bg-success",
        "parse_error": "bg-warning",
        "schema_error": "bg-warning",
    }
    cls = mapping.get(status, "bg-secondary")
    return f'<span class="badge {cls}">{_esc(status)}</span>'


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
        return '<span class="text-muted">None</span>'
    return _esc(repr(val))


def _css_safe(name: str) -> str:
    """Replace characters that are unsafe in CSS selectors with hyphens."""
    return re.sub(r"[^a-zA-Z0-9_-]", "-", str(name))


def _field_row_class(score: float, status: str) -> str:
    if status == "ignored":
        return "table-secondary"
    if score >= 1.0:
        return "table-success"
    if score <= 0.0:
        return "table-danger"
    return "table-warning"


def _render_step_diff(
    case_name: str, step_name: str, expected: Any, actual: Any
) -> str:
    """Render a side-by-side HTML diff of expected vs actual values."""
    exp_str = yaml.dump(
        expected, sort_keys=False, allow_unicode=True, default_flow_style=False,
        Dumper=yaml.SafeDumper,
    )
    act_str = yaml.dump(
        actual, sort_keys=False, allow_unicode=True, default_flow_style=False,
        Dumper=yaml.SafeDumper,
    )
    differ = difflib.HtmlDiff(tabsize=2)
    table = differ.make_table(
        [html.escape(line) for line in exp_str.splitlines(keepends=True)],
        [html.escape(line) for line in act_str.splitlines(keepends=True)],
        fromdesc=f"Expected — {_esc(step_name)}",
        todesc=f"Actual — {_esc(step_name)}",
        context=True,
        numlines=_DIFF_CONTEXT_LINES,
    )
    safe_id = _css_safe(f"diff-{case_name}-{step_name}")
    return (
        f'<div class="diff-collapse mt-2" id="{safe_id}">'
        f'<div class="diff-table mb-3">{table}</div>'
        f"</div>"
    )


# ── PDF export ─────────────────────────────────────────────────────────────────

def _write_pdf(html: str, pdf_path: Path) -> None:
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "PDF export requires WeasyPrint.  Install it with:\n"
            "  pip install weasyprint"
        ) from exc
    HTML(string=html).write_pdf(str(pdf_path))


# ── HTML shell ─────────────────────────────────────────────────────────────────

_HTML_SHELL = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
    rel="stylesheet"
    integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH"
    crossorigin="anonymous">
  <style>
    body {{ font-family: system-ui, sans-serif; background: #f8f9fa; }}
    .card-header {{ background: #e9ecef; }}
    .mermaid {{ background: #fff; border: 1px solid #dee2e6; border-radius: 4px; padding: 1rem; }}
    table {{ font-size: .875rem; }}
    code {{ color: #6f42c1; }}
    .diff-table table {{ width: 100%; table-layout: fixed; }}
    .diff-table td {{ font-size: .8rem; vertical-align: top; word-break: break-all; }}
    .diff-table .diff_header {{ font-weight: 600; }}
    .diff-table .diff_next {{ display: none; }}
  </style>
</head>
<body>
<div class="container-fluid py-4" style="max-width:1200px">
  <h1 class="mb-1">{title}</h1>
  <p class="text-muted small mb-4">Generated: {timestamp}</p>
  {body}
</div>
<script
  src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"
  integrity="sha384-YvpcrYf0tY3lHB60NNkmXc4s9bIOgUxi8T/jzmfXyY5GVNtQ0wqKzgp4aovOJgSr"
  crossorigin="anonymous"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
</script>
<script>
{chart_js}
</script>
</body>
</html>"""
