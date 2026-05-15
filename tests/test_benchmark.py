"""Tests for BenchmarkRunner, BenchmarkSummary, and report generation."""
from __future__ import annotations

from pathlib import Path

import pytest

from pyconveyor.benchmark import BenchmarkRunner, BenchmarkSummary
from pyconveyor.report import ALL_SECTIONS, DEFAULT_SECTIONS, generate_report

PIPELINES = Path(__file__).parent / "fixtures" / "pipelines"
BENCHMARKS = Path(__file__).parent / "fixtures" / "benchmarks"


# ── BenchmarkRunner — case discovery ──────────────────────────────────────────

class TestCaseDiscovery:
    def test_discovers_valid_cases(self):
        runner = BenchmarkRunner(BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"])
        assert len(runner._cases) == 3

    def test_case_names_sorted(self):
        runner = BenchmarkRunner(BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"])
        names = [c["name"] for c in runner._cases]
        assert names == sorted(names)

    def test_missing_benchmark_dir_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            BenchmarkRunner(tmp_path / "nonexistent", pipelines=[PIPELINES / "hello.yaml"])

    def test_skips_dirs_without_both_files(self, tmp_path: Path):
        (tmp_path / "incomplete").mkdir()
        (tmp_path / "incomplete" / "input.json").write_text("{}")
        runner = BenchmarkRunner(tmp_path, pipelines=[PIPELINES / "hello.yaml"])
        assert runner._cases == []

    def test_ignores_non_directories(self, tmp_path: Path):
        (tmp_path / "stray_file.txt").write_text("hello")
        runner = BenchmarkRunner(tmp_path, pipelines=[PIPELINES / "hello.yaml"])
        assert runner._cases == []

    def test_discovers_yaml_case_files(self, tmp_path: Path):
        case = tmp_path / "case_yaml"
        case.mkdir()
        (case / "input.yaml").write_text('name: "Ada"\nlanguage: "French"\n')
        (case / "expected.yaml").write_text(
            'greet:\n  message: "Bonjour Ada!"\n  language: "French"\n'
        )

        runner = BenchmarkRunner(tmp_path, pipelines=[PIPELINES / "hello.yaml"])
        assert len(runner._cases) == 1
        assert runner._cases[0]["name"] == "case_yaml"

    def test_raises_when_multiple_input_formats_exist(self, tmp_path: Path):
        case = tmp_path / "case_conflict"
        case.mkdir()
        (case / "input.json").write_text('{"name":"Ada"}')
        (case / "input.yaml").write_text('name: "Ada"\n')
        (case / "expected.json").write_text('{"greet": {"message": "x", "language": "y"}}')

        with pytest.raises(ValueError, match="multiple input files"):
            BenchmarkRunner(tmp_path, pipelines=[PIPELINES / "hello.yaml"])

    def test_input_file_ref_expands_markdown_text(self, tmp_path: Path):
        case = tmp_path / "case_file"
        case.mkdir()
        (case / "paper.md").write_text("# Title\nBody")
        (case / "input.yaml").write_text(
            "name: Ada\n"
            "language: French\n"
            "paper:\n"
            "  $file: paper.md\n"
            "nested:\n"
            "  refs:\n"
            "    - $file: paper.md\n"
        )
        (case / "expected.yaml").write_text(
            'greet:\n  message: "Bonjour Ada!"\n  language: "French"\n'
        )

        runner = BenchmarkRunner(tmp_path, pipelines=[PIPELINES / "hello.yaml"])
        loaded = runner._cases[0]["input"]
        assert loaded["paper"] == "# Title\nBody"
        assert loaded["nested"]["refs"][0] == "# Title\nBody"


# ── BenchmarkRunner — scoring ──────────────────────────────────────────────────

class TestScoring:
    def _run(self, tmp_path: Path, expected: dict) -> BenchmarkSummary:
        case = tmp_path / "case_01"
        case.mkdir()
        import json
        (case / "input.json").write_text(json.dumps({"name": "Ada", "language": "French"}))
        (case / "expected.json").write_text(json.dumps(expected))
        runner = BenchmarkRunner(tmp_path, pipelines=[PIPELINES / "hello.yaml"])
        return runner.run()

    def test_exact_match_scores_1(self, tmp_path: Path):
        s = self._run(tmp_path, {"greet": {"message": "Bonjour Ada!", "language": "French"}})
        pr = s.pipelines[0]
        case = pr.cases[0]
        assert case.overall_score == 1.0
        assert case.step_scores["greet"].score == 1.0

    def test_all_fields_wrong_scores_0(self, tmp_path: Path):
        s = self._run(tmp_path, {"greet": {"message": "Hello!", "language": "English"}})
        pr = s.pipelines[0]
        assert pr.cases[0].step_scores["greet"].score == 0.0

    def test_partial_field_match(self, tmp_path: Path):
        s = self._run(tmp_path, {"greet": {"message": "Wrong", "language": "French"}})
        pr = s.pipelines[0]
        # message wrong (0.0), language correct (1.0) → mean = 0.5
        assert pr.cases[0].step_scores["greet"].score == pytest.approx(0.5)

    def test_field_scores_populated(self, tmp_path: Path):
        s = self._run(tmp_path, {"greet": {"message": "Bonjour Ada!", "language": "Wrong"}})
        ss = s.pipelines[0].cases[0].step_scores["greet"]
        by_field = {f.field: f.score for f in ss.field_scores}
        assert by_field["greet.message"] == 1.0
        assert by_field["greet.language"] == 0.0

    def test_missing_step_scores_0(self, tmp_path: Path):
        s = self._run(tmp_path, {"nonexistent_step": {"x": "y"}})
        ss = s.pipelines[0].cases[0].step_scores["nonexistent_step"]
        assert ss.score == 0.0
        assert ss.status == "missing"

    def test_custom_step_comparator(self, tmp_path: Path):
        case = tmp_path / "c"
        case.mkdir()
        import json
        (case / "input.json").write_text(json.dumps({"name": "Ada", "language": "French"}))
        (case / "expected.json").write_text(json.dumps({"greet": "ANYTHING"}))
        runner = BenchmarkRunner(
            tmp_path,
            pipelines=[PIPELINES / "hello.yaml"],
            comparators={"greet": lambda a, e: 0.75},
        )
        s = runner.run()
        assert s.pipelines[0].cases[0].step_scores["greet"].score == pytest.approx(0.75)

    def test_custom_field_comparator(self, tmp_path: Path):
        case = tmp_path / "c"
        case.mkdir()
        import json
        (case / "input.json").write_text(json.dumps({"name": "Ada", "language": "French"}))
        (case / "expected.json").write_text(json.dumps({"greet": {"message": "bonjour ada!", "language": "french"}}))
        runner = BenchmarkRunner(
            tmp_path,
            pipelines=[PIPELINES / "hello.yaml"],
            comparators={
                "greet.message": lambda a, e: float(str(a).lower() == str(e).lower()),
                "greet.language": lambda a, e: float(str(a).lower() == str(e).lower()),
            },
        )
        s = runner.run()
        assert s.pipelines[0].cases[0].step_scores["greet"].score == pytest.approx(1.0)

    def test_scalar_expected_exact_match(self, tmp_path: Path):
        import json
        case = tmp_path / "c"
        case.mkdir()
        (case / "input.json").write_text(json.dumps({"name": "Ada", "language": "French"}))
        # greet step returns a Pydantic model; comparing to a scalar → 0.0
        (case / "expected.json").write_text(json.dumps({"greet": "exact_string"}))
        runner = BenchmarkRunner(tmp_path, pipelines=[PIPELINES / "hello.yaml"])
        s = runner.run()
        # Pydantic model != string → 0.0
        assert s.pipelines[0].cases[0].step_scores["greet"].score == 0.0


# ── BenchmarkRunner — aggregation ─────────────────────────────────────────────

class TestAggregation:
    def test_step_mean_accuracy(self):
        runner = BenchmarkRunner(BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"])
        s = runner.run()
        pr = s.pipelines[0]
        # 3 cases: correct (1.0), wrong (0.0), partial (0.5) → mean = 0.5
        assert pr.step_mean_accuracy["greet"] == pytest.approx(0.5)

    def test_overall_mean_accuracy(self):
        runner = BenchmarkRunner(BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"])
        s = runner.run()
        pr = s.pipelines[0]
        # overall per case: 1.0, 0.0, 0.5 → mean = 0.5
        assert pr.overall_mean_accuracy == pytest.approx(0.5)

    def test_pass_rate_default_threshold(self):
        runner = BenchmarkRunner(BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"])
        s = runner.run()
        pr = s.pipelines[0]
        # Only 1 of 3 cases scores 1.0 on greet step
        assert pr.step_pass_rate["greet"] == pytest.approx(1 / 3)

    def test_pass_rate_custom_threshold(self):
        runner = BenchmarkRunner(
            BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"], pass_threshold=0.4
        )
        s = runner.run()
        pr = s.pipelines[0]
        # cases with score >= 0.4: correct (1.0) and partial (0.5) → 2/3
        assert pr.step_pass_rate["greet"] == pytest.approx(2 / 3)

    def test_summary_case_names(self):
        runner = BenchmarkRunner(BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"])
        s = runner.run()
        assert s.case_names == sorted(["case_greeting_correct", "case_greeting_wrong", "case_greeting_partial"])

    def test_pass_threshold_stored(self):
        runner = BenchmarkRunner(BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"], pass_threshold=0.8)
        s = runner.run()
        assert s.pass_threshold == pytest.approx(0.8)


# ── BenchmarkRunner — error handling ──────────────────────────────────────────

class TestErrorHandling:
    def test_pipeline_error_case_status(self, tmp_path: Path):
        import json
        case = tmp_path / "c"
        case.mkdir()
        (case / "input.json").write_text(json.dumps({"name": "Ada", "language": "French"}))
        (case / "expected.json").write_text(json.dumps({"greet": {"message": "x", "language": "y"}}))

        bad_pipeline = tmp_path / "bad.yaml"
        bad_pipeline.write_text(
            "models:\n"
            "  m:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses: ['NOT JSON']\n"
            "steps:\n"
            "  - name: greet\n"
            "    type: llm\n"
            "    model: m\n"
            "    schema: tests.fixtures.schemas:Greeting\n"
            "    prompt_string: hi\n"
            "    max_attempts: 1\n"
        )
        runner = BenchmarkRunner(tmp_path, pipelines=[bad_pipeline])
        s = runner.run()
        case_result = s.pipelines[0].cases[0]
        assert case_result.status == "error"
        assert case_result.error is not None

    def test_error_case_score_is_zero(self, tmp_path: Path):
        import json
        case = tmp_path / "c"
        case.mkdir()
        (case / "input.json").write_text(json.dumps({}))
        (case / "expected.json").write_text(json.dumps({"greet": {"message": "x", "language": "y"}}))

        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "models:\n"
            "  m:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses: ['not json']\n"
            "steps:\n"
            "  - name: greet\n"
            "    type: llm\n"
            "    model: m\n"
            "    schema: tests.fixtures.schemas:Greeting\n"
            "    prompt_string: hi\n"
            "    max_attempts: 1\n"
        )
        runner = BenchmarkRunner(tmp_path, pipelines=[bad])
        s = runner.run()
        assert s.pipelines[0].cases[0].overall_score == 0.0

    def test_continues_after_error(self, tmp_path: Path):
        import json

        for i, (msg, lang) in enumerate([("Bonjour Ada!", "French"), ("Hello!", "English")]):
            c = tmp_path / f"case_{i:02d}"
            c.mkdir()
            (c / "input.json").write_text(json.dumps({"name": "Ada", "language": "French"}))
            (c / "expected.json").write_text(json.dumps({"greet": {"message": msg, "language": lang}}))

        runner = BenchmarkRunner(tmp_path, pipelines=[PIPELINES / "hello.yaml"])
        s = runner.run()
        assert len(s.pipelines[0].cases) == 2


# ── Multi-pipeline comparison ──────────────────────────────────────────────────

class TestMultiPipeline:
    def test_two_pipelines_in_summary(self):
        runner = BenchmarkRunner(
            BENCHMARKS,
            pipelines=[PIPELINES / "hello.yaml", PIPELINES / "hello.yaml"],
        )
        s = runner.run()
        assert len(s.pipelines) == 2

    def test_same_pipeline_same_scores(self):
        runner = BenchmarkRunner(
            BENCHMARKS,
            pipelines=[PIPELINES / "hello.yaml", PIPELINES / "hello.yaml"],
        )
        s = runner.run()
        p1, p2 = s.pipelines
        assert p1.overall_mean_accuracy == pytest.approx(p2.overall_mean_accuracy)


# ── Report generation ──────────────────────────────────────────────────────────

class TestReportGeneration:
    def _summary(self) -> BenchmarkSummary:
        runner = BenchmarkRunner(BENCHMARKS, pipelines=[PIPELINES / "hello.yaml"])
        return runner.run()

    def test_report_creates_file(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        assert out.exists()

    def test_report_is_html(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        content = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content

    def test_report_contains_pipeline_name(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        assert "hello.yaml" in out.read_text(encoding="utf-8")

    def test_report_contains_case_names(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "case_greeting_correct" in html
        assert "case_greeting_wrong" in html

    def test_report_custom_title(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out, title="My Custom Report")
        assert "My Custom Report" in out.read_text(encoding="utf-8")

    def test_report_sections_filter(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out, sections=["overall_summary"])
        html = out.read_text(encoding="utf-8")
        assert 'id="overall_summary"' in html
        assert 'id="per_step_accuracy"' not in html

    def test_attempt_logs_off_by_default(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        assert 'id="attempt_logs"' not in out.read_text(encoding="utf-8")

    def test_attempt_logs_on_when_requested(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out, sections=DEFAULT_SECTIONS + ["attempt_logs"])
        assert 'id="attempt_logs"' in out.read_text(encoding="utf-8")

    def test_pipeline_comparison_only_with_multi(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out, sections=["pipeline_comparison"])
        # Only 1 pipeline — comparison section should not appear
        assert 'id="pipeline_comparison"' not in out.read_text(encoding="utf-8")

    def test_mermaid_graph_present(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out, sections=["mermaid_graph"])
        html = out.read_text(encoding="utf-8")
        assert "mermaid" in html
        assert "flowchart TD" in html

    def test_mermaid_graph_contains_accuracy(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        generate_report(s, output=out, sections=["mermaid_graph"])
        html = out.read_text(encoding="utf-8")
        assert "accuracy:" in html

    def test_two_pipeline_report_has_comparison(self, tmp_path: Path):
        runner = BenchmarkRunner(
            BENCHMARKS,
            pipelines=[PIPELINES / "hello.yaml", PIPELINES / "hello.yaml"],
        )
        s = runner.run()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        assert 'id="pipeline_comparison"' in out.read_text(encoding="utf-8")

    def test_pdf_requires_weasyprint(self, tmp_path: Path):
        s = self._summary()
        out = tmp_path / "report.html"
        try:
            import weasyprint  # noqa: F401
        except ImportError:
            with pytest.raises(ImportError, match="WeasyPrint"):
                generate_report(s, output=out, pdf=True)

    def test_all_sections_constant(self):
        assert "attempt_logs" in ALL_SECTIONS
        assert "overall_summary" in ALL_SECTIONS

    def test_default_sections_excludes_attempt_logs(self):
        assert "attempt_logs" not in DEFAULT_SECTIONS


# ── CLI integration ────────────────────────────────────────────────────────────

class TestCLI:
    def test_benchmark_cli_entrypoint(self, tmp_path: Path):
        import subprocess
        import sys

        out = tmp_path / "report.html"
        hello = str(PIPELINES / "hello.yaml")
        bench = str(BENCHMARKS)
        out_str = str(out)
        script = (
            "from pyconveyor.cli import main; import sys; "
            f"sys.argv = ['pyconveyor', 'benchmark', '{bench}', "
            f"'--pipeline', '{hello}', '--report', '{out_str}']; main()"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert out.exists()

    def test_benchmark_cli_missing_dir(self, tmp_path: Path):
        import subprocess
        import sys

        hello = str(PIPELINES / "hello.yaml")
        missing = str(tmp_path / "nonexistent")
        script = (
            "from pyconveyor.cli import main; import sys; "
            f"sys.argv = ['pyconveyor', 'benchmark', '{missing}', "
            f"'--pipeline', '{hello}']; main()"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


# ── Graph with scores ──────────────────────────────────────────────────────────

class TestGraphWithScores:
    def test_score_appears_in_label(self, tmp_path: Path):
        from pyconveyor.graph import generate_mermaid

        pipeline = tmp_path / "p.yaml"
        pipeline.write_text(
            "models:\n"
            "  m:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses: ['ok']\n"
            "steps:\n"
            "  - name: greet\n"
            "    type: llm\n"
            "    model: m\n"
            "    prompt_string: hi\n"
        )
        diagram = generate_mermaid(pipeline, step_scores={"greet": 0.87})
        assert "accuracy: 87%" in diagram

    def test_no_scores_unchanged(self, tmp_path: Path):
        from pyconveyor.graph import _label

        step = {"name": "test", "type": "llm"}
        label_no_score = _label(step)
        label_with_score = _label(step, score=0.5)
        assert "accuracy" not in label_no_score
        assert "accuracy: 50%" in label_with_score


# ── $ignore sentinel ────────────────────────────────────────────────────────


class TestIgnoreSentinel:
    """Tests for the ``$ignore`` sentinel and related scoring changes."""

    def _run(self, tmp_path: Path, expected: dict) -> BenchmarkSummary:
        case = tmp_path / "case_01"
        case.mkdir()
        import json

        (case / "input.json").write_text(
            json.dumps({"name": "Ada", "language": "French"})
        )
        (case / "expected.json").write_text(json.dumps(expected))
        runner = BenchmarkRunner(tmp_path, pipelines=[PIPELINES / "hello.yaml"])
        return runner.run()

    # ── Field-level $ignore ─────────────────────────────────────────────────

    def test_single_field_ignore_excluded_from_mean(self, tmp_path: Path):
        """One $ignore field doesn't affect the step score denominator."""
        s = self._run(
            tmp_path,
            {"greet": {"message": "Bonjour Ada!", "language": "$ignore"}},
        )
        ss = s.pipelines[0].cases[0].step_scores["greet"]
        assert ss.status == "scored"
        assert ss.score == 1.0  # only message scored, language excluded

    def test_all_fields_ignore_step_ignored(self, tmp_path: Path):
        """When every field is $ignore, the step is excluded from scoring."""
        s = self._run(
            tmp_path,
            {"greet": {"message": "$ignore", "language": "$ignore"}},
        )
        ss = s.pipelines[0].cases[0].step_scores["greet"]
        assert ss.status == "ignored"
        # Overall score should not include this step
        assert s.pipelines[0].cases[0].overall_score == 0.0

    def test_mixed_scored_and_ignored_fields(self, tmp_path: Path):
        """Scored and ignored fields mix correctly in the mean."""
        s = self._run(
            tmp_path,
            {"greet": {"message": "Wrong", "language": "French", "notes": "$ignore"}},
        )
        ss = s.pipelines[0].cases[0].step_scores["greet"]
        assert ss.status == "scored"
        # message=0.0, language=1.0, notes=ignored → mean = (0+1)/2 = 0.5
        assert ss.score == pytest.approx(0.5)
        # Verify field statuses
        statuses = {f.field: f.status for f in ss.field_scores}
        assert statuses["greet.notes"] == "ignored"
        assert statuses["greet.message"] == "scored"

    # ── Step-level $ignore ──────────────────────────────────────────────────

    def test_step_level_ignore(self, tmp_path: Path):
        """``"stepname": "$ignore"`` excludes the whole step."""
        s = self._run(tmp_path, {"greet": "$ignore"})
        ss = s.pipelines[0].cases[0].step_scores["greet"]
        assert ss.status == "ignored"
        assert s.pipelines[0].cases[0].overall_score == 0.0

    def test_step_ignored_plus_scored_step(self, tmp_path: Path):
        """An ignored step alongside a scored step."""
        case = tmp_path / "c"
        case.mkdir()
        import json

        (case / "input.json").write_text(
            json.dumps({"name": "Ada", "language": "French"})
        )
        (case / "expected.json").write_text(
            json.dumps({
                "greet": "$ignore",
                "greet_scored": {"message": "Bonjour Ada!", "language": "French"},
            })
        )
        # Need a pipeline with both steps — create one
        pipeline = tmp_path / "p.yaml"
        pipeline.write_text(
            "models:\n"
            "  m:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"message": "Bonjour Ada!", "language": "French"}\'\n'
            "steps:\n"
            "  - name: greet\n"
            "    type: llm\n"
            "    model: m\n"
            "    prompt_string: hi\n"
            "  - name: greet_scored\n"
            "    type: llm\n"
            "    model: m\n"
            "    prompt_string: hi\n"
        )
        runner = BenchmarkRunner(tmp_path, pipelines=[pipeline])
        s = runner.run()
        case_result = s.pipelines[0].cases[0]
        assert case_result.step_scores["greet"].status == "ignored"
        assert case_result.step_scores["greet_scored"].status == "scored"
        # Only greet_scored counts → overall = 1.0
        assert case_result.overall_score == 1.0

    # ── Nested dict $ignore ────────────────────────────────────────────────

    def test_nested_dict_ignore(self, tmp_path: Path):
        """$ignore works inside nested dicts with recursive scoring."""
        expected = {
            "greet": {
                "meta": {
                    "source": "mock",
                    "notes": "$ignore",
                },
                "message": "Bonjour Ada!",
            }
        }
        s = self._run(tmp_path, expected)
        ss = s.pipelines[0].cases[0].step_scores["greet"]
        assert ss.status == "scored"
        # Fields: meta.source, meta.notes (ignored), message
        # meta.source → "mock" in actual? Need to check actual output
        field_statuses = {f.field: f.status for f in ss.field_scores}
        assert field_statuses["greet.meta.notes"] == "ignored"

    # ── Empty containers ────────────────────────────────────────────────────

    def test_empty_dict_ignored(self, tmp_path: Path):
        """An empty dict ``{}`` as expected gives status ignored."""
        s = self._run(tmp_path, {"greet": {}})
        ss = s.pipelines[0].cases[0].step_scores["greet"]
        assert ss.status == "ignored"

    # ── Top-level $ignore error ─────────────────────────────────────────────

    def test_top_level_ignore_raises(self, tmp_path: Path):
        """Bare '$ignore' as expected file content raises ValueError."""
        case = tmp_path / "c"
        case.mkdir()
        import json

        (case / "input.json").write_text(json.dumps({"name": "Ada"}))
        (case / "expected.json").write_text(json.dumps("$ignore"))
        with pytest.raises(ValueError, match="bare"):
            BenchmarkRunner(tmp_path, pipelines=[PIPELINES / "hello.yaml"])

    # ── Custom comparator interaction ───────────────────────────────────────

    def test_custom_comparator_skipped_for_ignore(self, tmp_path: Path):
        """Custom comparator is NOT called when expected value is $ignore."""
        case = tmp_path / "c"
        case.mkdir()
        import json

        (case / "input.json").write_text(
            json.dumps({"name": "Ada", "language": "French"})
        )
        (case / "expected.json").write_text(
            json.dumps({"greet": {"message": "$ignore", "language": "French"}})
        )
        called = []

        def tracker(a, e):
            called.append(1)
            return 1.0

        runner = BenchmarkRunner(
            tmp_path,
            pipelines=[PIPELINES / "hello.yaml"],
            comparators={"greet.message": tracker},
        )
        s = runner.run()
        assert len(called) == 0  # comparator not invoked for $ignore field
        ss = s.pipelines[0].cases[0].step_scores["greet"]
        assert ss.score == 1.0  # only language scored (matches), message ignored

    # ── Aggregation excludes ignored steps ──────────────────────────────────

    def test_ignored_step_not_in_aggregation(self, tmp_path: Path):
        """Ignored steps are excluded from step_mean_accuracy."""
        case = tmp_path / "c"
        case.mkdir()
        import json

        (case / "input.json").write_text(
            json.dumps({"name": "Ada", "language": "French"})
        )
        (case / "expected.json").write_text(json.dumps({"greet": "$ignore"}))
        runner = BenchmarkRunner(tmp_path, pipelines=[PIPELINES / "hello.yaml"])
        s = runner.run()
        pr = s.pipelines[0]
        assert "greet" not in pr.step_mean_accuracy


# ── List matching ───────────────────────────────────────────────────────────


class TestListMatching:
    """Tests for set-overlap, $ordered positional, and best-match list scoring."""

    def _make_pipeline(self, tmp_path: Path, mock_response: str) -> Path:
        """Create a pipeline that returns a specific JSON value."""
        pipeline = tmp_path / "p.yaml"
        pipeline.write_text(
            "models:\n"
            "  m:\n"
            "    provider: mock\n"
            "    model: m\n"
            f"    mock_responses: ['{mock_response}']\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: m\n"
            "    prompt_string: hi\n"
        )
        return pipeline

    def _run_case(self, tmp_path: Path, expected: dict) -> BenchmarkSummary:
        case = tmp_path / "c"
        case.mkdir()
        import json

        (case / "input.json").write_text("{}")
        (case / "expected.json").write_text(json.dumps(expected))
        return BenchmarkRunner(tmp_path, pipelines=[self._pipeline]).run()

    # ── Set-based overlap (default for scalar lists) ────────────────────────

    def test_set_overlap_order_independent(self, tmp_path: Path):
        """Order doesn't matter for scalar lists."""
        self._pipeline = self._make_pipeline(
            tmp_path, '{"items": ["milk", "egg", "butter"]}'
        )
        s = self._run_case(tmp_path, {"extract": {"items": ["egg", "milk"]}})
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.status == "scored"
        assert ss.score == 1.0  # "egg" and "milk" both present

    def test_set_overlap_partial(self, tmp_path: Path):
        """Missing elements reduce the score."""
        self._pipeline = self._make_pipeline(
            tmp_path, '{"items": ["egg"]}'
        )
        s = self._run_case(tmp_path, {"extract": {"items": ["egg", "milk"]}})
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == 0.5  # 1 of 2 expected matched

    def test_set_overlap_duplicates(self, tmp_path: Path):
        """Duplicate handling via Counter."""
        self._pipeline = self._make_pipeline(
            tmp_path, '{"items": ["egg", "egg", "milk"]}'
        )
        s = self._run_case(tmp_path, {"extract": {"items": ["egg", "egg"]}})
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == 1.0  # both expected "egg"s matched

    # ── $ignore in scalar lists ─────────────────────────────────────────────

    def test_scalar_list_ignore_consumes_extra(self, tmp_path: Path):
        """$ignore consumes one unmatched actual element."""
        self._pipeline = self._make_pipeline(
            tmp_path, '{"items": ["milk", "egg", "butter"]}'
        )
        s = self._run_case(
            tmp_path, {"extract": {"items": ["egg", "$ignore", "milk"]}}
        )
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == 1.0  # 2 real matches + 1 ignored wildcard satisfied

    def test_scalar_list_ignore_unsatisfied(self, tmp_path: Path):
        """$ignore without a spare actual reduces the score."""
        self._pipeline = self._make_pipeline(
            tmp_path, '{"items": ["egg", "milk"]}'
        )
        s = self._run_case(
            tmp_path, {"extract": {"items": ["egg", "$ignore", "milk"]}}
        )
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == pytest.approx(2 / 3)  # 2 real matches, 0 wildcard satisfied

    # ── $ordered positional matching ────────────────────────────────────────

    def test_ordered_positional_exact(self, tmp_path: Path):
        """$ordered compares element-by-element by position."""
        self._pipeline = self._make_pipeline(
            tmp_path, '{"items": [1, 2, 3]}'
        )
        s = self._run_case(
            tmp_path, {"extract": {"items": {"$ordered": [1, 2, 3]}}}
        )
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == 1.0

    def test_ordered_positional_mismatch(self, tmp_path: Path):
        """Order matters with $ordered — reversed list scores only overlapping positions."""
        self._pipeline = self._make_pipeline(
            tmp_path, '{"items": [3, 2, 1]}'
        )
        s = self._run_case(
            tmp_path, {"extract": {"items": {"$ordered": [1, 2, 3]}}}
        )
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        # pos 0: 1≠3=0, pos 1: 2=2=1, pos 2: 3≠1=0 → 1/3
        assert ss.score == pytest.approx(1 / 3)

    def test_ordered_with_ignore_wildcard(self, tmp_path: Path):
        """$ignore in $ordered list matches anything at that position."""
        self._pipeline = self._make_pipeline(
            tmp_path, '{"items": ["a", "any", "c"]}'
        )
        s = self._run_case(
            tmp_path,
            {"extract": {"items": {"$ordered": ["a", "$ignore", "c"]}}},
        )
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == 1.0

    def test_ordered_length_mismatch(self, tmp_path: Path):
        """Different lengths penalize via max_len denominator."""
        self._pipeline = self._make_pipeline(
            tmp_path, '{"items": [1, 2]}'
        )
        s = self._run_case(
            tmp_path, {"extract": {"items": {"$ordered": [1, 2, 3]}}}
        )
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == 2 / 3  # positions 0,1 match, position 2 missing

    # ── Best-match dict lists ───────────────────────────────────────────────

    def test_best_match_order_independent(self, tmp_path: Path):
        """Dict lists match greedily regardless of order."""
        self._pipeline = self._make_pipeline(
            tmp_path,
            '{"people": [{"name": "Bob"}, {"name": "Ada"}]}',
        )
        s = self._run_case(
            tmp_path,
            {"extract": {"people": [{"name": "Ada"}, {"name": "Bob"}]}},
        )
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == 1.0  # best-match pairs them correctly

    def test_best_match_partial_fields(self, tmp_path: Path):
        """Partial field matches in dict lists produce fractional scores."""
        self._pipeline = self._make_pipeline(
            tmp_path,
            '{"people": [{"name": "Ada", "age": 30}]}',
        )
        s = self._run_case(
            tmp_path,
            {"extract": {"people": [{"name": "Ada", "age": 25}]}},
        )
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == 0.5  # name matches, age doesn't

    def test_best_match_ignore_in_dict_field(self, tmp_path: Path):
        """$ignore as a field value inside a dict list element."""
        self._pipeline = self._make_pipeline(
            tmp_path,
            '{"people": [{"name": "Ada", "notes": "blah"}]}',
        )
        s = self._run_case(
            tmp_path,
            {
                "extract": {
                    "people": [{"name": "Ada", "notes": "$ignore"}]
                }
            },
        )
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == 1.0  # name matches, notes ignored

    def test_best_match_ignore_as_list_element(self, tmp_path: Path):
        """$ignore as a list element in dict list consumes best remaining."""
        self._pipeline = self._make_pipeline(
            tmp_path,
            '{"people": [{"name": "Ada"}, {"name": "Bob"}, {"name": "Carl"}]}',
        )
        s = self._run_case(
            tmp_path,
            {
                "extract": {
                    "people": [{"name": "Ada"}, "$ignore", {"name": "Bob"}]
                }
            },
        )
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        # Ada and Bob matched, $ignore consumes Carl → 3/3 = 1.0
        assert ss.score == 1.0

    def test_best_match_ignore_unsatisfied(self, tmp_path: Path):
        """$ignore list element without a spare actual penalizes."""
        self._pipeline = self._make_pipeline(
            tmp_path,
            '{"people": [{"name": "Ada"}]}',
        )
        s = self._run_case(
            tmp_path,
            {
                "extract": {
                    "people": [{"name": "Ada"}, "$ignore"]
                }
            },
        )
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == 0.5  # Ada matched, $ignore unfilled → 1/2

    def test_actual_not_a_list(self, tmp_path: Path):
        """When expected is a list but actual is not, score 0.0."""
        self._pipeline = self._make_pipeline(
            tmp_path, '"not a list"'
        )
        s = self._run_case(tmp_path, {"extract": ["a", "b"]})
        ss = s.pipelines[0].cases[0].step_scores["extract"]
        assert ss.score == 0.0


# ── Report helpers ─────────────────────────────────────────────────────────────


class TestReportHelpers:
    def test_css_safe_replaces_special_chars(self):
        from pyconveyor.report import _css_safe

        assert _css_safe("10.1128_mbio.00335-25") == "10-1128_mbio-00335-25"
        assert _css_safe("extract.primary") == "extract-primary"
        assert _css_safe("simple-name") == "simple-name"
        assert _css_safe("a[0]") == "a-0-"
        assert _css_safe("hello world") == "hello-world"

    def test_css_safe_keeps_safe_chars(self):
        from pyconveyor.report import _css_safe

        assert _css_safe("abc123_-") == "abc123_-"

    def test_match_icon_pass(self):
        from pyconveyor.report import _match_icon

        assert "✓" in _match_icon(1.0, "scored")
        assert "✗" in _match_icon(0.0, "scored")
        assert "~" in _match_icon(0.5, "scored")
        assert "—" in _match_icon(0.0, "ignored")

    def test_fmt_value_none(self):
        from pyconveyor.report import _fmt_value

        assert "—" in _fmt_value(None)

    def test_render_field_table_single_score_returns_empty(self):
        from pyconveyor.report import _render_field_table
        from pyconveyor.benchmark import FieldScore, StepScore

        ss = StepScore("greet", 1.0, "scored", [FieldScore("greet.msg", "hi", "hi", 1.0)])
        assert _render_field_table("greet", ss) == ""

    def test_report_contains_css_safe_ids(self, tmp_path: Path):
        from pyconveyor.benchmark import BenchmarkRunner
        from pyconveyor.report import generate_report

        pipelines = Path(__file__).parent / "fixtures" / "pipelines"
        benchmarks = Path(__file__).parent / "fixtures" / "benchmarks"
        runner = BenchmarkRunner(benchmarks, pipelines=[pipelines / "hello.yaml"])
        s = runner.run()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        # IDs should use css-safe versions — no dots in id attributes
        assert 'id="case-0-case_greeting' in html

    def test_report_contains_field_section(self, tmp_path: Path):
        from pyconveyor.benchmark import BenchmarkRunner
        from pyconveyor.report import generate_report

        pipelines = Path(__file__).parent / "fixtures" / "pipelines"
        benchmarks = Path(__file__).parent / "fixtures" / "benchmarks"
        runner = BenchmarkRunner(benchmarks, pipelines=[pipelines / "hello.yaml"])
        s = runner.run()
        out = tmp_path / "report.html"
        generate_report(s, output=out)
        html = out.read_text(encoding="utf-8")
        assert "step-section" in html


# ── CaseResult actuals/expecteds ────────────────────────────────────────────────


class TestCaseResultPayloads:
    def test_actuals_populated_for_success(self, tmp_path: Path):
        import json

        from pyconveyor.benchmark import BenchmarkRunner

        pipelines = Path(__file__).parent / "fixtures" / "pipelines"
        case = tmp_path / "c"
        case.mkdir()
        (case / "input.json").write_text(
            json.dumps({"name": "Ada", "language": "French"})
        )
        (case / "expected.json").write_text(
            json.dumps({"greet": {"message": "Bonjour Ada!", "language": "French"}})
        )
        runner = BenchmarkRunner(tmp_path, pipelines=[pipelines / "hello.yaml"])
        s = runner.run()
        cr = s.pipelines[0].cases[0]
        assert cr.actuals == {"greet": {"message": "Bonjour Ada!", "language": "French"}}
        assert cr.expecteds == {"greet": {"message": "Bonjour Ada!", "language": "French"}}

    def test_expecteds_is_copy_of_expected(self, tmp_path: Path):
        import json

        from pyconveyor.benchmark import BenchmarkRunner

        pipelines = Path(__file__).parent / "fixtures" / "pipelines"
        case = tmp_path / "c"
        case.mkdir()
        (case / "input.json").write_text(
            json.dumps({"name": "Ada", "language": "French"})
        )
        (case / "expected.json").write_text(
            json.dumps({"greet": "$ignore", "other": {"x": 1}})
        )
        runner = BenchmarkRunner(tmp_path, pipelines=[pipelines / "hello.yaml"])
        s = runner.run()
        cr = s.pipelines[0].cases[0]
        assert cr.expecteds == {"greet": "$ignore", "other": {"x": 1}}


# ── Benchmark output_format ─────────────────────────────────────────────────────


class TestBenchmarkOutputFormat:
    def test_input_format_tracked_per_case(self, tmp_path: Path):
        from pyconveyor.benchmark import BenchmarkRunner

        pipelines = Path(__file__).parent / "fixtures" / "pipelines"
        case = tmp_path / "c"
        case.mkdir()
        (case / "input.yaml").write_text("name: Ada\nlanguage: French\n")
        (case / "expected.yaml").write_text(
            "greet:\n  message: Bonjour Ada!\n  language: French\n"
        )
        runner = BenchmarkRunner(tmp_path, pipelines=[pipelines / "hello.yaml"])
        assert runner._cases[0]["_input_format"] == "yaml"

    def test_cli_output_format_override(self, tmp_path: Path):
        from pyconveyor.benchmark import BenchmarkRunner

        pipelines = Path(__file__).parent / "fixtures" / "pipelines"
        case = tmp_path / "c"
        case.mkdir()
        (case / "input.yaml").write_text("name: Ada\nlanguage: French\n")
        (case / "expected.yaml").write_text(
            "greet:\n  message: Bonjour Ada!\n  language: French\n"
        )
        runner = BenchmarkRunner(
            tmp_path,
            pipelines=[pipelines / "hello.yaml"],
            output_format="json",
        )
        summary = runner.run()
        cr = summary.pipelines[0].cases[0]
        assert cr.status == "ok"

    def test_output_format_injected_into_case_input(self, tmp_path: Path):
        from pyconveyor.benchmark import BenchmarkRunner

        pipelines = Path(__file__).parent / "fixtures" / "pipelines"
        case = tmp_path / "c"
        case.mkdir()
        (case / "input.yaml").write_text("name: Ada\nlanguage: French\n")
        (case / "expected.yaml").write_text(
            "greet:\n  message: Bonjour Ada!\n  language: French\n"
        )
        runner = BenchmarkRunner(
            tmp_path,
            pipelines=[pipelines / "hello.yaml"],
            output_format="yaml",
        )
        summary = runner.run()
        cr = summary.pipelines[0].cases[0]
        assert cr.status == "ok"
