"""CLI smoke tests — no real LLM calls, mock provider only."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from pyconveyor.cli import main

PIPELINES_DIR = Path(__file__).parent / "fixtures" / "pipelines"


def _run_cli(*args: str) -> tuple[int, str]:
    """Run the CLI with the given arguments and capture stdout/stderr."""
    import io

    captured_out = io.StringIO()
    captured_err = io.StringIO()
    exit_code = 0

    with patch("sys.argv", ["pyconveyor", *args]):
        with patch("sys.stdout", captured_out):
            with patch("sys.stderr", captured_err):
                try:
                    main()
                except SystemExit as e:
                    exit_code = e.code or 0

    output = captured_out.getvalue() + captured_err.getvalue()
    return exit_code, output


class TestCliHelp:
    def test_help_exits_zero(self) -> None:
        code, _ = _run_cli("--help")
        assert code == 0

    def test_help_mentions_commands(self) -> None:
        code, output = _run_cli("--help")
        assert "run" in output
        assert "validate" in output
        assert "init" in output


class TestCliValidate:
    def test_validate_ok(self, tmp_path: Path) -> None:
        """Validate a schema-less pipeline (no Pydantic import needed)."""
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"ok": true}\'\n'
            "steps:\n"
            "  - name: step1\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt: 'Hello'\n"
        )
        code, output = _run_cli("validate", str(pipeline))
        assert code == 0
        assert "valid" in output.lower()

    def test_validate_missing_file(self, tmp_path: Path) -> None:
        code, output = _run_cli("validate", str(tmp_path / "nope.yaml"))
        assert code != 0


class TestCliSchema:
    def test_schema_outputs_json(self) -> None:
        code, output = _run_cli("schema")
        assert code == 0
        parsed = json.loads(output)
        assert "properties" in parsed


class TestCliVisualise:
    def test_visualise_outputs_mermaid(self, tmp_path: Path) -> None:
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"ok": true}\'\n'
            "steps:\n"
            "  - name: step1\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt: 'Hello'\n"
        )
        code, output = _run_cli("visualise", str(pipeline))
        assert code == 0
        assert "mermaid" in output.lower() or "flowchart" in output.lower()


class TestCliInit:
    def test_init_creates_files(self, tmp_path: Path) -> None:
        target = tmp_path / "myproject"
        code, output = _run_cli("init", str(target))
        assert code == 0
        assert (target / "pipeline.yaml").exists()
        assert (target / "schemas.py").exists()
        assert (target / "prompts" / "extract.j2").exists()

    def test_init_existing_dir_skips_gracefully(self, tmp_path: Path) -> None:
        """Running init twice should not crash."""
        code1, _ = _run_cli("init", str(tmp_path))
        code2, _ = _run_cli("init", str(tmp_path))
        assert code2 == 0


class TestCliRun:
    _PIPELINE_YAML = (
        "models:\n"
        "  default:\n"
        "    provider: mock\n"
        "    model: m\n"
        "    mock_responses:\n"
        '      - \'{"value": 42}\'\n'
        "steps:\n"
        "  - name: step1\n"
        "    type: llm\n"
        "    model: default\n"
        "    prompt_string: 'Extract something'\n"
    )

    def test_run_inline_json_input(self, tmp_path: Path) -> None:
        """Regression: ISSUE-004 — --input should accept inline JSON strings."""
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(self._PIPELINE_YAML)
        # This used to crash with FileNotFoundError when input started with '{'
        code, output = _run_cli("run", str(pipeline), "--input", '{"doc": "hello"}')
        assert code == 0
        result = json.loads(output)
        assert "steps" in result

    def test_run_json_file_input(self, tmp_path: Path) -> None:
        """--input also accepts a file path."""
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(self._PIPELINE_YAML)
        input_file = tmp_path / "input.json"
        input_file.write_text('{"doc": "hello"}')
        code, output = _run_cli("run", str(pipeline), "--input", str(input_file))
        assert code == 0
        result = json.loads(output)
        assert "steps" in result

    def test_run_dry_run(self, tmp_path: Path) -> None:
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(self._PIPELINE_YAML)
        code, output = _run_cli(
            "run", str(pipeline), "--input", '{"doc": "hello"}', "--dry-run"
        )
        assert code == 0
        result = json.loads(output)
        assert result["steps"]["step1"] is None

    def test_run_local_schema_importable(self, tmp_path: Path) -> None:
        """Regression: ISSUE-003 — local schemas.py must be importable from pipeline dir."""
        schema_py = tmp_path / "schemas.py"
        schema_py.write_text(
            "from pydantic import BaseModel\n\n"
            "class Out(BaseModel):\n"
            "    value: int\n"
        )
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"value": 42}\'\n'
            "steps:\n"
            "  - name: step1\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract'\n"
            "    schema: schemas:Out\n"
        )
        # This used to fail with "No module named 'schemas'"
        code, output = _run_cli("run", str(pipeline), "--input", '{"doc": "hello"}')
        assert code == 0
        result = json.loads(output)
        assert result["steps"]["step1"]["value"] == 42


class TestCliBatch:
    _PIPELINE_YAML = (
        "models:\n"
        "  default:\n"
        "    provider: mock\n"
        "    model: m\n"
        "    mock_responses:\n"
        '      - \'{"value": 42}\'\n'
        "steps:\n"
        "  - name: step1\n"
        "    type: llm\n"
        "    model: default\n"
        "    prompt_string: 'Extract something'\n"
    )

    def _write_pipeline(self, tmp_path: Path) -> Path:
        p = tmp_path / "pipeline.yaml"
        p.write_text(self._PIPELINE_YAML)
        return p

    def _write_jsonl(self, tmp_path: Path, items: list[dict]) -> Path:
        p = tmp_path / "items.jsonl"
        p.write_text("\n".join(json.dumps(obj) for obj in items))
        return p

    def test_batch_basic(self, tmp_path: Path) -> None:
        pipeline = self._write_pipeline(tmp_path)
        items_file = self._write_jsonl(tmp_path, [{"id": "a"}, {"id": "b"}])
        code, output = _run_cli(
            "batch", str(pipeline), "--input", str(items_file), "--no-progress"
        )
        assert code == 0
        lines = [ln for ln in output.strip().splitlines() if ln.strip()]
        assert len(lines) == 2
        for ln in lines:
            record = json.loads(ln)
            assert record["ok"] is True
            assert "steps" in record

    def test_batch_output_file(self, tmp_path: Path) -> None:
        pipeline = self._write_pipeline(tmp_path)
        items_file = self._write_jsonl(tmp_path, [{"id": "x"}])
        out_file = tmp_path / "results.jsonl"
        code, output = _run_cli(
            "batch", str(pipeline),
            "--input", str(items_file),
            "--output", str(out_file),
            "--no-progress",
        )
        assert code == 0
        assert out_file.exists()
        record = json.loads(out_file.read_text().strip())
        assert record["ok"] is True

    def test_batch_invalid_json_line_exits_1(self, tmp_path: Path) -> None:
        pipeline = self._write_pipeline(tmp_path)
        bad_file = tmp_path / "bad.jsonl"
        bad_file.write_text('{"id": "a"}\nnot-json\n')
        code, output = _run_cli(
            "batch", str(pipeline), "--input", str(bad_file), "--no-progress"
        )
        assert code == 1

    def test_batch_empty_input_exits_1(self, tmp_path: Path) -> None:
        pipeline = self._write_pipeline(tmp_path)
        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("")
        code, output = _run_cli(
            "batch", str(pipeline), "--input", str(empty_file), "--no-progress"
        )
        assert code == 1

    def test_batch_custom_key(self, tmp_path: Path) -> None:
        pipeline = self._write_pipeline(tmp_path)
        items_file = self._write_jsonl(tmp_path, [{"doc_id": "doc-1"}])
        code, output = _run_cli(
            "batch", str(pipeline),
            "--input", str(items_file),
            "--key", "doc_id",
            "--no-progress",
        )
        assert code == 0
        lines = [ln for ln in output.strip().splitlines() if ln.strip()]
        record = json.loads(lines[0])
        assert record["doc_id"] == "doc-1"

    def test_batch_dry_run(self, tmp_path: Path) -> None:
        pipeline = self._write_pipeline(tmp_path)
        items_file = self._write_jsonl(tmp_path, [{"id": "a"}])
        code, output = _run_cli(
            "batch", str(pipeline),
            "--input", str(items_file),
            "--dry-run",
            "--no-progress",
        )
        assert code == 0
        lines = [ln for ln in output.strip().splitlines() if ln.strip()]
        record = json.loads(lines[0])
        assert record["ok"] is True

    def test_batch_non_dict_jsonl_line_exits_1(self, tmp_path: Path) -> None:
        # Regression: JSONL line that is valid JSON but not an object (e.g. array) must exit 1
        pipeline = self._write_pipeline(tmp_path)
        items_file = tmp_path / "bad.jsonl"
        items_file.write_text('["not", "an", "object"]\n')
        code, output = _run_cli(
            "batch", str(pipeline), "--input", str(items_file), "--no-progress"
        )
        assert code == 1
        assert "not a JSON object" in output

    def test_batch_blank_lines_skipped(self, tmp_path: Path) -> None:
        # Blank lines in JSONL are skipped; one valid item should succeed
        pipeline = self._write_pipeline(tmp_path)
        items_file = tmp_path / "blanks.jsonl"
        items_file.write_text('\n{"id": "a"}\n\n')
        code, output = _run_cli(
            "batch", str(pipeline), "--input", str(items_file), "--no-progress"
        )
        assert code == 0
        lines = [ln for ln in output.strip().splitlines() if ln.strip()]
        assert len(lines) == 1

    def test_batch_failed_item_shows_error(self, tmp_path: Path) -> None:
        # When a pipeline item fails, output record has ok=False and error field
        from unittest.mock import patch

        from pyconveyor import PipelineRunner
        pipeline = self._write_pipeline(tmp_path)
        items_file = self._write_jsonl(tmp_path, [{"id": "fail-item"}])
        with patch.object(PipelineRunner, "run", side_effect=RuntimeError("pipeline boom")):
            code, output = _run_cli(
                "batch", str(pipeline), "--input", str(items_file), "--no-progress"
            )
        assert code == 0  # batch exits 0 even with failures (check ok field)
        lines = [ln for ln in output.strip().splitlines() if ln.strip()]
        record = json.loads(lines[0])
        assert record["ok"] is False
        assert "pipeline boom" in record["error"]

