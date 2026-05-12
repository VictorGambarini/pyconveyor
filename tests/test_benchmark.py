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
        assert by_field["message"] == 1.0
        assert by_field["language"] == 0.0

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
