"""Tests for report.py helper functions and HTML output.

Covers: _reorder_to_expected, _fmt_value, _match_icon, _render_field_table,
and end-to-end generate_report with field comparison view.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyconveyor.benchmark import BenchmarkRunner, BenchmarkSummary, FieldScore, StepScore, CaseResult, PipelineBenchmarkResult
from pyconveyor.report import generate_report, _reorder_to_expected, _fmt_value, _match_icon, _render_field_table

# ── Fixtures ───────────────────────────────────────────────────────────────────

BENCHMARKS = Path(__file__).parent / "fixtures" / "benchmarks"
PIPELINES = Path(__file__).parent / "fixtures" / "pipelines"


def _make_summary(field_scores: list[FieldScore] | None = None) -> BenchmarkSummary:
    """Build a minimal BenchmarkSummary with one case/step for report tests."""
    fs = field_scores or []
    step_score_val = (
        sum(f.score for f in fs if f.status == "scored") / max(1, sum(1 for f in fs if f.status == "scored"))
        if fs else 1.0
    )
    ss = StepScore(
        step_name="greet",
        score=step_score_val,
        status="scored",
        field_scores=fs,
    )
    case = CaseResult(
        case_name="test_case",
        pipeline_path="test.yaml",
        status="ok",
        step_scores={"greet": ss},
        overall_score=step_score_val,
        error=None,
        elapsed_seconds=0.1,
        actuals={"greet": {"message": "hello", "language": "en"}},
        expecteds={"greet": {"message": "hello", "language": "en"}},
    )
    pr = PipelineBenchmarkResult(
        pipeline_path="test.yaml",
        cases=[case],
        step_mean_accuracy={"greet": step_score_val},
        step_pass_rate={"greet": 1.0},
        overall_mean_accuracy=step_score_val,
        overall_pass_rate=1.0,
    )
    return BenchmarkSummary(
        pipelines=[pr],
        case_names=["test_case"],
        pass_threshold=0.8,
    )


# ── _reorder_to_expected ──────────────────────────────────────────────────────

class TestReorderToExpected:
    def test_simple_reorder(self):
        actual = {"b": 2, "a": 1, "c": 3}
        expected = {"a": None, "b": None, "c": None}
        result = _reorder_to_expected(actual, expected)
        assert list(result.keys()) == ["a", "b", "c"]

    def test_extra_actual_keys_at_end(self):
        actual = {"b": 2, "a": 1, "extra": 99}
        expected = {"a": None, "b": None}
        result = _reorder_to_expected(actual, expected)
        assert list(result.keys()) == ["a", "b", "extra"]

    def test_missing_actual_key_skipped(self):
        actual = {"a": 1}
        expected = {"a": None, "b": None}
        result = _reorder_to_expected(actual, expected)
        assert list(result.keys()) == ["a"]

    def test_nested_reorder(self):
        actual = {"outer": {"z": 3, "y": 2, "x": 1}}
        expected = {"outer": {"x": None, "y": None, "z": None}}
        result = _reorder_to_expected(actual, expected)
        assert list(result["outer"].keys()) == ["x", "y", "z"]

    def test_non_dict_unchanged(self):
        assert _reorder_to_expected("hello", "world") == "hello"
        assert _reorder_to_expected([1, 2], [3, 4]) == [1, 2]
        assert _reorder_to_expected(None, {"a": 1}) is None

    def test_actual_not_dict_expected_dict(self):
        assert _reorder_to_expected("not_a_dict", {"a": 1}) == "not_a_dict"

    def test_preserves_values(self):
        actual = {"b": 99, "a": 42}
        expected = {"a": 0, "b": 0}
        result = _reorder_to_expected(actual, expected)
        assert result["a"] == 42
        assert result["b"] == 99


# ── _fmt_value ────────────────────────────────────────────────────────────────

class TestFmtValue:
    def test_none_returns_dash(self):
        result = _fmt_value(None)
        assert "—" in result
        assert 'class="muted"' in result

    def test_scalar_string(self):
        result = _fmt_value("hello world")
        assert "hello world" in result
        assert "<code" in result

    def test_scalar_integer(self):
        result = _fmt_value(42)
        assert "42" in result

    def test_dict_uses_yaml_inline(self):
        result = _fmt_value({"key": "value"})
        # YAML inline format uses {key: value}
        assert "key" in result
        assert "value" in result
        assert "<code" in result

    def test_list_uses_yaml_inline(self):
        result = _fmt_value(["a", "b", "c"])
        assert "a" in result
        assert "<code" in result

    def test_short_value_no_expand_button(self):
        result = _fmt_value("short")
        assert "val-expand" not in result
        assert "val-short" not in result

    def test_long_value_gets_expand_toggle(self):
        long_val = "x" * 200
        result = _fmt_value(long_val)
        assert "val-short" in result
        assert "val-expand" in result
        assert 'aria-label="Show full value"' in result
        assert "val-full" in result

    def test_truncate_at_120_by_default(self):
        val = "a" * 121
        result = _fmt_value(val)
        # The short text should be the first 120 chars + ellipsis
        assert "a" * 120 + "…" in result

    def test_custom_truncate(self):
        val = "b" * 50
        result = _fmt_value(val, truncate=20)
        assert "val-expand" in result

    def test_html_escaping(self):
        result = _fmt_value("<script>alert(1)</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_ampersand_escaped(self):
        result = _fmt_value("a & b")
        assert "&amp;" in result


# ── _match_icon ───────────────────────────────────────────────────────────────

class TestMatchIcon:
    def test_pass_icon(self):
        result = _match_icon(1.0, "scored")
        assert 'aria-label="pass"' in result
        assert "✓" in result
        assert "icon-pass" in result

    def test_fail_icon(self):
        result = _match_icon(0.0, "scored")
        assert 'aria-label="fail"' in result
        assert "✗" in result
        assert "icon-fail" in result

    def test_partial_icon(self):
        result = _match_icon(0.5, "scored")
        assert 'aria-label="partial"' in result
        assert "~" in result
        assert "icon-warn" in result

    def test_ignored_icon(self):
        result = _match_icon(0.0, "ignored")
        assert 'aria-label="ignored"' in result
        assert "icon-ignored" in result


# ── _render_field_table ───────────────────────────────────────────────────────

class TestRenderFieldTable:
    def _make_ss(self, field_scores: list[FieldScore]) -> StepScore:
        score = (
            sum(f.score for f in field_scores if f.status == "scored")
            / max(1, sum(1 for f in field_scores if f.status == "scored"))
        )
        return StepScore(step_name="greet", score=score, status="scored", field_scores=field_scores)

    def test_empty_field_scores_returns_empty(self):
        ss = StepScore(step_name="greet", score=1.0, status="scored", field_scores=[])
        assert _render_field_table("greet", ss) == ""

    def test_single_field_score_returns_empty(self):
        ss = self._make_ss([FieldScore("greet.msg", "hi", "hi", 1.0)])
        assert _render_field_table("greet", ss) == ""

    def test_fail_rows_before_pass_rows(self):
        fs = [
            FieldScore("greet.a", "x", "y", 0.0),  # fail
            FieldScore("greet.b", "ok", "ok", 1.0),  # pass
            FieldScore("greet.c", "z", "w", 0.0),  # fail
        ]
        result = _render_field_table("greet", self._make_ss(fs))
        fail_pos_a = result.index("greet.a")
        fail_pos_c = result.index("greet.c")
        # 'b' is in the pass details section, which comes after fail rows
        # Find where greet.b appears relative to greet.a
        assert fail_pos_a < result.index("greet.b")
        assert fail_pos_c < result.index("greet.b")

    def test_passing_rows_inside_details(self):
        fs = [
            FieldScore("greet.a", "x", "y", 0.0),
            FieldScore("greet.b", "ok", "ok", 1.0),
        ]
        result = _render_field_table("greet", self._make_ss(fs))
        # pass row should be inside a <details> element
        details_pos = result.index("<details>")
        pass_pos = result.index("greet.b")
        assert details_pos < pass_pos

    def test_ignored_rows_in_pass_group(self):
        """$ignore fields are not failures — they go in the passing group."""
        fs = [
            FieldScore("greet.a", "x", "y", 0.0),  # fail
            FieldScore("greet.b", "?", "$ignore", 0.0, status="ignored"),  # ignored
        ]
        result = _render_field_table("greet", self._make_ss(fs))
        # greet.b is not a fail (ignored), so it goes in the pass/ignored group
        pass_summary_pos = result.index("pass-summary")
        b_pos = result.index("greet.b")
        assert pass_summary_pos < b_pos

    def test_pass_summary_shows_count(self):
        fs = [
            FieldScore("greet.a", "x", "y", 0.0),  # fail
            FieldScore("greet.b", "ok", "ok", 1.0),  # pass
            FieldScore("greet.c", "ok", "ok", 1.0),  # pass
        ]
        result = _render_field_table("greet", self._make_ss(fs))
        assert "2 passing fields" in result

    def test_pass_summary_singular(self):
        fs = [
            FieldScore("greet.a", "x", "y", 0.0),  # fail
            FieldScore("greet.b", "ok", "ok", 1.0),  # 1 pass
        ]
        result = _render_field_table("greet", self._make_ss(fs))
        assert "1 passing field" in result
        assert "1 passing fields" not in result

    def test_all_fail_no_details_element(self):
        fs = [
            FieldScore("greet.a", "x", "y", 0.0),
            FieldScore("greet.b", "m", "n", 0.0),
        ]
        result = _render_field_table("greet", self._make_ss(fs))
        assert "<details>" not in result

    def test_field_path_in_output(self):
        fs = [
            FieldScore("greet.message", "hi", "hello", 0.0),
            FieldScore("greet.language", "en", "en", 1.0),
        ]
        result = _render_field_table("greet", self._make_ss(fs))
        assert "greet.message" in result
        assert "greet.language" in result

    def test_expected_and_actual_columns(self):
        fs = [
            FieldScore("greet.msg", "hello", "world", 0.0),
            FieldScore("greet.lang", "en", "en", 1.0),
        ]
        result = _render_field_table("greet", self._make_ss(fs))
        # Both expected and actual values should appear
        assert "hello" in result
        assert "world" in result


# ── End-to-end report generation ──────────────────────────────────────────────

class TestReportFieldComparison:
    def _summary_with_fields(self) -> BenchmarkSummary:
        fs = [
            FieldScore("greet.message", "hi", "hello", 0.0),  # fail
            FieldScore("greet.language", "en", "en", 1.0),    # pass
            FieldScore("greet.punctuation", "!", "!", 1.0),   # pass
        ]
        return _make_summary(field_scores=fs)

    def test_field_table_present_in_html(self, tmp_path: Path):
        s = self._summary_with_fields()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "field-table" in html

    def test_field_paths_in_html(self, tmp_path: Path):
        s = self._summary_with_fields()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "greet.message" in html
        assert "greet.language" in html

    def test_step_section_present(self, tmp_path: Path):
        s = self._summary_with_fields()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "step-section" in html

    def test_expected_column_before_actual(self, tmp_path: Path):
        s = self._summary_with_fields()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        expected_pos = html.index(">Expected<")
        actual_pos = html.index(">Actual<")
        assert expected_pos < actual_pos

    def test_no_diff_section_in_output(self, tmp_path: Path):
        """Regression: YAML text diff should be gone from the report."""
        runner = BenchmarkRunner(BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"])
        s = runner.run()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "diff-section" not in html
        assert "Output Diff" not in html
        assert "diff-side" not in html
        assert "diff-unified" not in html

    def test_no_diff_functions_in_html(self, tmp_path: Path):
        """Regression: diff function CSS classes should not appear."""
        runner = BenchmarkRunner(BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"])
        s = runner.run()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "wdiff-add" not in html
        assert "wdiff-del" not in html

    def test_match_icons_present(self, tmp_path: Path):
        s = self._summary_with_fields()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert 'aria-label="pass"' in html
        assert 'aria-label="fail"' in html

    def test_pass_collapse_present(self, tmp_path: Path):
        s = self._summary_with_fields()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "pass-summary" in html
        assert "<details>" in html

    def test_single_field_score_no_field_table(self, tmp_path: Path):
        """Steps with only one FieldScore use the compact step table, not the field table."""
        fs = [FieldScore("greet.message", "hi", "hello", 0.0)]
        s = _make_summary(field_scores=fs)
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        # The CSS defines .field-table but no HTML element with that class should be emitted
        assert 'class="field-table"' not in html

    def test_fmt_value_in_simple_step_table(self, tmp_path: Path):
        """For steps with 0-1 FieldScores, values are fmt_value formatted (YAML inline for dicts)."""
        fs = []  # no field scores -> simple table
        s = _make_summary(field_scores=fs)
        # actual/expected are dicts, should appear in YAML inline format not repr()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        # Should NOT have Python repr-style {'key': 'value'}
        assert "{'message':" not in html
        # Should have YAML inline or plain monospace code
        assert "<code" in html
