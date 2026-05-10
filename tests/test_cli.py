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

    def test_batch_reserved_key_exits_1(self, tmp_path: Path) -> None:
        # Regression: --key ok|error|steps would silently overwrite output fields
        pipeline = self._write_pipeline(tmp_path)
        items_file = self._write_jsonl(tmp_path, [{"ok": "x"}])
        code, output = _run_cli(
            "batch", str(pipeline), "--input", str(items_file),
            "--key", "ok", "--no-progress",
        )
        assert code == 1
        assert "reserved" in output.lower() or "conflict" in output.lower()


# ── Feature 1: inline schema — CLI tests ─────────────────────────────────────

class TestCliInlineSchema:
    def _inline_pipeline(self, tmp_path: Path) -> Path:
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"title": "Hi"}\'\n'
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema:\n"
            "      title: str\n"
        )
        return pipeline

    def test_validate_passes_with_inline_dict_schema(self, tmp_path: Path) -> None:
        pipeline = self._inline_pipeline(tmp_path)
        code, output = _run_cli("validate", str(pipeline))
        assert code == 0
        assert "valid" in output.lower()

    def test_schema_emit_includes_oneof_on_schema_field(self) -> None:
        code, output = _run_cli("schema")
        assert code == 0
        parsed = json.loads(output)
        schema_field = parsed["definitions"]["Step"]["properties"]["schema"]
        assert "oneOf" in schema_field


# ── Feature 3: schema infer — CLI tests ───────────────────────────────────────

class TestCliSchemaInfer:
    def _simple_pipeline(self, tmp_path: Path) -> Path:
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - "{}"\n'
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
        )
        return pipeline

    def test_schema_infer_exits_0_and_prints_source(self, tmp_path: Path) -> None:
        pipeline = self._simple_pipeline(tmp_path)
        sample = tmp_path / "sample.json"
        sample.write_text('{"title": "hello", "score": 1}')
        code, output = _run_cli("schema", "infer", str(pipeline), "--sample", str(sample))
        assert code == 0
        assert "class ExtractSchema(BaseModel):" in output

    def test_schema_infer_output_file(self, tmp_path: Path) -> None:
        pipeline = self._simple_pipeline(tmp_path)
        sample = tmp_path / "sample.json"
        sample.write_text('{"title": "hi"}')
        out = tmp_path / "schemas_out.py"
        code, output = _run_cli(
            "schema", "infer", str(pipeline), "--sample", str(sample), "--output", str(out)
        )
        assert code == 0
        assert out.exists()
        assert "class ExtractSchema(BaseModel):" in out.read_text()

    def test_schema_infer_jsonl_warns_and_uses_first(self, tmp_path: Path) -> None:
        pipeline = self._simple_pipeline(tmp_path)
        sample = tmp_path / "results.jsonl"
        sample.write_text('{"title": "first"}\n{"title": "second"}\n')
        code, output = _run_cli("schema", "infer", str(pipeline), "--sample", str(sample))
        assert code == 0
        assert "Warning" in output or "warning" in output
        assert "class ExtractSchema(BaseModel):" in output

    def test_schema_infer_non_dict_json_exits_nonzero(self, tmp_path: Path) -> None:
        pipeline = self._simple_pipeline(tmp_path)
        sample = tmp_path / "sample.json"
        sample.write_text('[1, 2, 3]')
        code, output = _run_cli("schema", "infer", str(pipeline), "--sample", str(sample))
        assert code != 0
        assert "Error" in output

    def test_schema_infer_missing_sample_exits_nonzero(self, tmp_path: Path) -> None:
        pipeline = self._simple_pipeline(tmp_path)
        code, output = _run_cli(
            "schema", "infer", str(pipeline), "--sample", str(tmp_path / "missing.json")
        )
        assert code != 0
        assert "Error" in output

    def test_schema_emit_subcommand_still_works(self) -> None:
        code, output = _run_cli("schema", "emit")
        assert code == 0
        parsed = json.loads(output)
        assert "properties" in parsed

    def test_schema_bare_still_works(self) -> None:
        code, output = _run_cli("schema")
        assert code == 0
        parsed = json.loads(output)
        assert "properties" in parsed

    def test_schema_infer_step_override(self, tmp_path: Path) -> None:
        pipeline = self._simple_pipeline(tmp_path)
        sample = tmp_path / "sample.json"
        sample.write_text('{"score": 42}')
        code, output = _run_cli(
            "schema", "infer", str(pipeline), "--sample", str(sample),
            "--step", "my_custom_step",
        )
        assert code == 0
        assert "class MyCustomStepSchema(BaseModel):" in output

    def test_first_llm_step_name_exception_returns_extract(self, tmp_path: Path) -> None:
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text("not: [valid: yaml: [\n")  # invalid YAML → exception path
        sample = tmp_path / "sample.json"
        sample.write_text('{"title": "x"}')
        code, output = _run_cli(
            "schema", "infer", str(pipeline), "--sample", str(sample),
        )
        assert code == 0
        assert "class ExtractSchema(BaseModel):" in output


# ── Feature 5: interactive init — CLI tests ───────────────────────────────────

class TestCliInitInteractive:
    def _run_interactive(
        self, tmp_path: Path, inputs: list[str]
    ) -> tuple[int, str]:
        from unittest.mock import patch

        target = tmp_path / "project"
        with patch("builtins.input", side_effect=inputs):
            return _run_cli("init", str(target), "--interactive")

    def test_full_session_writes_pipeline_with_inline_schema(self, tmp_path: Path) -> None:
        code, _ = self._run_interactive(
            tmp_path,
            [
                "articles",           # subject
                "title:str",          # field 1
                "score:int | None",   # field 2
                "",                   # done
                "1",                  # provider: OpenAI
            ],
        )
        assert code == 0
        pipeline_text = (tmp_path / "project" / "pipeline.yaml").read_text()
        assert "title: str" in pipeline_text
        assert "score: int | None" in pipeline_text

    def test_pipeline_does_not_contain_string_schema_ref(self, tmp_path: Path) -> None:
        code, _ = self._run_interactive(
            tmp_path,
            ["docs", "title:str", "", "1"],
        )
        assert code == 0
        text = (tmp_path / "project" / "pipeline.yaml").read_text()
        assert "schema: schemas:" not in text

    def test_schemas_py_not_written(self, tmp_path: Path) -> None:
        self._run_interactive(tmp_path, ["docs", "title:str", "", "1"])
        assert not (tmp_path / "project" / "schemas.py").exists()

    def test_prompt_template_written_with_schema_hint(self, tmp_path: Path) -> None:
        self._run_interactive(tmp_path, ["docs", "title:str", "", "1"])
        tmpl = (tmp_path / "project" / "prompts" / "extract.j2").read_text()
        assert "schema_hint" in tmpl

    def test_invalid_field_name_skipped(self, tmp_path: Path) -> None:
        code, _ = self._run_interactive(
            tmp_path,
            [
                "docs",
                "123bad:str",   # invalid identifier → skipped
                "title:str",    # valid
                "",
                "1",
            ],
        )
        assert code == 0
        text = (tmp_path / "project" / "pipeline.yaml").read_text()
        assert "title: str" in text
        assert "123bad" not in text

    def test_empty_fields_falls_back_to_default(self, tmp_path: Path) -> None:
        code, _ = self._run_interactive(
            tmp_path,
            ["docs", "", "1"],  # no fields entered
        )
        assert code == 0
        text = (tmp_path / "project" / "pipeline.yaml").read_text()
        assert "title: str" in text
        assert "key_points: list[str]" in text

    def test_provider_choice_2_produces_anthropic(self, tmp_path: Path) -> None:
        self._run_interactive(tmp_path, ["docs", "title:str", "", "2"])
        text = (tmp_path / "project" / "pipeline.yaml").read_text()
        assert "provider: anthropic" in text

    def test_provider_choice_3_produces_ollama(self, tmp_path: Path) -> None:
        self._run_interactive(tmp_path, ["docs", "title:str", "", "3"])
        text = (tmp_path / "project" / "pipeline.yaml").read_text()
        assert "provider: openai_compat" in text
        assert "11434" in text

    def test_static_init_unchanged(self, tmp_path: Path) -> None:
        target = tmp_path / "static_project"
        code, _ = _run_cli("init", str(target))
        assert code == 0
        assert (target / "schemas.py").exists()
        assert (target / "pipeline.yaml").exists()

    def test_unknown_provider_choice_falls_back_to_openai(self, tmp_path: Path) -> None:
        code, _ = self._run_interactive(
            tmp_path,
            ["docs", "title:str", "", "99"],  # 99 is not a valid choice → defaults to OpenAI
        )
        assert code == 0
        text = (tmp_path / "project" / "pipeline.yaml").read_text()
        assert "provider: openai" in text or "provider: openai_compat" in text

    def test_field_without_colon_is_skipped(self, tmp_path: Path) -> None:
        code, _ = self._run_interactive(
            tmp_path,
            [
                "docs",
                "nocoion",   # no colon → skipped
                "title:str",
                "",
                "1",
            ],
        )
        assert code == 0
        text = (tmp_path / "project" / "pipeline.yaml").read_text()
        assert "title: str" in text
        assert "nocoion" not in text

