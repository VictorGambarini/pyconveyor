"""Tests for report.py helper functions and HTML output.

Covers: _flatten_leaves, _to_serialisable, _build_comp_data,
_render_comparison_block, and end-to-end generate_report with the interactive
field comparison table.
"""
from __future__ import annotations

from pathlib import Path

from pyconveyor.benchmark import (
    BenchmarkRunner,
    BenchmarkSummary,
    CaseResult,
    FieldScore,
    PipelineBenchmarkResult,
    StepScore,
)
from pyconveyor.report import (
    _build_comp_data,
    _flatten_leaves,
    _render_comparison_block,
    _to_serialisable,
    generate_report,
)

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


# ── _flatten_leaves ───────────────────────────────────────────────────────────


class TestFlattenLeaves:
    def test_flat_dict(self):
        result = _flatten_leaves({"a": 1, "b": 2})
        assert ("a", 1) in result
        assert ("b", 2) in result
        assert len(result) == 2

    def test_nested_dict(self):
        result = _flatten_leaves({"outer": {"inner": 42}})
        assert ("outer.inner", 42) in result
        assert len(result) == 1

    def test_list_indexed(self):
        result = _flatten_leaves([10, 20])
        assert ("[0]", 10) in result
        assert ("[1]", 20) in result

    def test_list_of_dicts(self):
        result = _flatten_leaves([{"a": 1}, {"a": 2}])
        assert ("[0].a", 1) in result
        assert ("[1].a", 2) in result

    def test_scalar_with_prefix(self):
        result = _flatten_leaves(42, "the.field")
        assert result == [("the.field", 42)]

    def test_scalar_without_prefix_returns_empty(self):
        result = _flatten_leaves(99)
        assert result == []

    def test_none_with_prefix(self):
        result = _flatten_leaves(None, "x")
        assert result == [("x", None)]

    def test_empty_dict_with_prefix(self):
        result = _flatten_leaves({}, "x")
        assert result == [("x", None)]

    def test_empty_list_with_prefix(self):
        result = _flatten_leaves([], "x")
        assert result == [("x", None)]

    def test_empty_dict_no_prefix_returns_empty(self):
        assert _flatten_leaves({}) == []

    def test_empty_list_no_prefix_returns_empty(self):
        assert _flatten_leaves([]) == []

    def test_deeply_nested(self):
        val = {"a": {"b": {"c": "leaf"}}}
        result = _flatten_leaves(val)
        assert result == [("a.b.c", "leaf")]

    def test_prefix_prepended(self):
        result = _flatten_leaves({"x": 1}, prefix="root")
        assert result == [("root.x", 1)]

    def test_boolean_and_float(self):
        result = _flatten_leaves({"flag": True, "score": 0.95})
        assert ("flag", True) in result
        assert ("score", 0.95) in result

    def test_string_value(self):
        result = _flatten_leaves({"name": "Bacillus subtilis"})
        assert ("name", "Bacillus subtilis") in result


# ── _to_serialisable ──────────────────────────────────────────────────────────


class TestToSerialisable:
    def test_none(self):
        assert _to_serialisable(None) is None

    def test_bool(self):
        assert _to_serialisable(True) is True

    def test_int(self):
        assert _to_serialisable(42) == 42

    def test_float(self):
        assert _to_serialisable(3.14) == 3.14

    def test_str(self):
        assert _to_serialisable("hello") == "hello"

    def test_other_converts_to_str(self):
        result = _to_serialisable(object())
        assert isinstance(result, str)

    def test_list_converts_to_str(self):
        result = _to_serialisable([1, 2, 3])
        assert isinstance(result, str)


# ── _build_comp_data ──────────────────────────────────────────────────────────


class TestBuildCompData:
    def _make_case(
        self,
        actuals: dict | None = None,
        expecteds: dict | None = None,
    ) -> CaseResult:
        if actuals is None:
            actuals = {"greet": {"message": "hello"}}
        if expecteds is None:
            expecteds = {"greet": {"message": "hello"}}
        return CaseResult(
            case_name="c",
            pipeline_path="p.yaml",
            status="ok",
            step_scores={},
            overall_score=1.0,
            error=None,
            elapsed_seconds=0.0,
            actuals=actuals,
            expecteds=expecteds,
        )

    def test_gold_key_present(self):
        c = self._make_case()
        data, options = _build_comp_data(c)
        assert "gold__greet" in data

    def test_step_key_present(self):
        c = self._make_case()
        data, options = _build_comp_data(c)
        assert "step__greet" in data

    def test_gold_flattened(self):
        c = self._make_case(
            actuals={"greet": {"a": 1}},
            expecteds={"greet": {"x": {"y": 2}}},
        )
        data, _ = _build_comp_data(c)
        assert data["gold__greet"] == {"x.y": 2}

    def test_step_flattened(self):
        c = self._make_case(
            actuals={"greet": {"items": ["alpha", "beta"]}},
            expecteds={"greet": {}},
        )
        data, _ = _build_comp_data(c)
        assert "items[0]" in data["step__greet"]
        assert data["step__greet"]["items[0]"] == "alpha"

    def test_options_order_gold_first(self):
        c = self._make_case()
        _, options = _build_comp_data(c)
        keys = [o["key"] for o in options]
        gold_idx = next(i for i, k in enumerate(keys) if k.startswith("gold__"))
        step_idx = next(i for i, k in enumerate(keys) if k.startswith("step__"))
        assert gold_idx < step_idx

    def test_none_actual_skipped(self):
        c = self._make_case(
            actuals={"greet": None, "other": {"x": 1}},
            expecteds={"greet": {}},
        )
        data, _ = _build_comp_data(c)
        assert "step__greet" not in data
        assert "step__other" in data

    def test_options_label_format(self):
        c = self._make_case()
        _, options = _build_comp_data(c)
        labels = {o["key"]: o["label"] for o in options}
        assert labels["gold__greet"] == "Gold: greet"
        assert labels["step__greet"] == "Step: greet"

    def test_multiple_steps(self):
        c = self._make_case(
            actuals={"step1": {"a": 1}, "step2": {"b": 2}},
            expecteds={"step1": {"a": 1}},
        )
        data, options = _build_comp_data(c)
        assert "gold__step1" in data
        assert "step__step1" in data
        assert "step__step2" in data


# ── _render_comparison_block ──────────────────────────────────────────────────


class TestRenderComparisonBlock:
    def _make_case(self, actuals=None, expecteds=None):
        if actuals is None:
            actuals = {"greet": {"message": "hello"}}
        if expecteds is None:
            expecteds = {"greet": {"message": "hello"}}
        return CaseResult(
            case_name="c",
            pipeline_path="p.yaml",
            status="ok",
            step_scores={},
            overall_score=1.0,
            error=None,
            elapsed_seconds=0.0,
            actuals=actuals,
            expecteds=expecteds,
        )

    def test_returns_string(self):
        c = self._make_case()
        result = _render_comparison_block(c, "mycase")
        assert isinstance(result, str)

    def test_contains_json_script_tag(self):
        c = self._make_case()
        result = _render_comparison_block(c, "mycase")
        assert 'type="application/json"' in result
        assert "comp-json-" in result

    def test_contains_left_right_selects(self):
        c = self._make_case()
        result = _render_comparison_block(c, "mycase")
        assert "comp-left" in result
        assert "comp-right" in result

    def test_contains_filter_select(self):
        c = self._make_case()
        result = _render_comparison_block(c, "mycase")
        assert "comp-filter" in result
        assert "All fields" in result
        assert "Differences only" in result

    def test_contains_comp_table(self):
        c = self._make_case()
        result = _render_comparison_block(c, "mycase")
        assert "comp-table" in result
        assert "comp-tbody-" in result

    def test_columns_in_header(self):
        c = self._make_case()
        result = _render_comparison_block(c, "mycase")
        assert "Field" in result
        assert "Left" in result
        assert "Right" in result
        assert "Status" in result

    def test_comp_init_called(self):
        c = self._make_case()
        result = _render_comparison_block(c, "mycase")
        assert "compInit(" in result

    def test_gold_in_options(self):
        c = self._make_case()
        result = _render_comparison_block(c, "mycase")
        assert "Gold: greet" in result

    def test_step_in_options(self):
        c = self._make_case()
        result = _render_comparison_block(c, "mycase")
        assert "Step: greet" in result

    def test_empty_data_returns_empty(self):
        c = self._make_case(actuals={}, expecteds={})
        result = _render_comparison_block(c, "mycase")
        assert result == ""

    def test_html_escaped_case_id(self):
        """Case IDs with special chars are CSS-safe'd."""
        c = self._make_case()
        result = _render_comparison_block(c, "case/with.special:chars")
        # No raw / or : should be injected into element IDs
        assert 'id="comp-json-case-with-special-chars"' in result

    def test_case_id_used_in_tbody(self):
        c = self._make_case()
        result = _render_comparison_block(c, "testid")
        assert 'id="comp-tbody-testid"' in result

    def test_json_data_contains_flattened_paths(self):
        import json

        c = self._make_case(
            actuals={"greet": {"nested": {"value": 42}}},
            expecteds={"greet": {"nested": {"value": 99}}},
        )
        result = _render_comparison_block(c, "x")
        # extract JSON from <script type="application/json"> tag
        start = result.index(">", result.index('type="application/json"')) + 1
        end = result.index("</script>", start)
        data = json.loads(result[start:end])
        assert "step__greet" in data
        assert "nested.value" in data["step__greet"]
        assert data["step__greet"]["nested.value"] == 42


# ── End-to-end report generation ──────────────────────────────────────────────


class TestReportEndToEnd:
    def test_report_generates_html(self, tmp_path: Path):
        s = _make_summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        assert out.exists()
        html = out.read_text(encoding="utf-8")
        assert "<!doctype html>" in html.lower() or "<html" in html.lower()

    def test_comparison_block_in_html(self, tmp_path: Path):
        s = _make_summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "comp-block" in html

    def test_field_paths_in_html(self, tmp_path: Path):
        s = _make_summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        # flat paths from actuals/expecteds should appear
        assert "message" in html
        assert "language" in html

    def test_comp_init_js_called(self, tmp_path: Path):
        s = _make_summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "compInit(" in html

    def test_comp_table_sortable_headers(self, tmp_path: Path):
        s = _make_summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "compSort(" in html

    def test_no_yaml_diff_in_output(self, tmp_path: Path):
        """Regression: old YAML diff markup should not be present."""
        s = _make_summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "yaml-diff" not in html
        assert "diff-del" not in html
        assert "diff-add" not in html

    def test_no_old_diff_side_classes(self, tmp_path: Path):
        """Regression: removed diff CSS classes absent from output."""
        runner = BenchmarkRunner(BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"])
        s = runner.run()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "wdiff-add" not in html
        assert "wdiff-del" not in html
        assert "diff-section" not in html

    def test_score_details_collapsible(self, tmp_path: Path):
        """Benchmark score summary is inside a <details> element."""
        fs = [
            FieldScore("greet.message", "hi", "hello", 0.0),
            FieldScore("greet.language", "en", "en", 1.0),
        ]
        s = _make_summary(field_scores=fs)
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "score-details" in html
        assert "<details" in html

    def test_json_embedded_in_case_card(self, tmp_path: Path):
        """Per-case JSON blob is embedded in <script type=application/json>."""
        s = _make_summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert 'type="application/json"' in html

    def test_error_block_shown(self, tmp_path: Path):
        """Cases with an error show the error-block."""
        ss = StepScore(step_name="greet", score=0.0, status="missing", field_scores=[])
        case = CaseResult(
            case_name="err_case",
            pipeline_path="test.yaml",
            status="error",
            step_scores={"greet": ss},
            overall_score=0.0,
            error="Something went wrong",
            elapsed_seconds=0.0,
            actuals={},
            expecteds={},
        )
        pr = PipelineBenchmarkResult(
            pipeline_path="test.yaml",
            cases=[case],
            step_mean_accuracy={},
            step_pass_rate={},
            overall_mean_accuracy=0.0,
            overall_pass_rate=0.0,
        )
        s = BenchmarkSummary(pipelines=[pr], case_names=["err_case"], pass_threshold=0.8)
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "error-block" in html
        assert "Something went wrong" in html

