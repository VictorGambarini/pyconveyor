"""Tests for the outputs: block — automatic step result saving."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyconveyor import PipelineRunner
from pyconveyor.errors import PipelineLoadError, StepConfigError

PIPELINES = Path(__file__).parent / "fixtures" / "pipelines"
GREET_J2 = (PIPELINES / "greet.j2").read_text()


def _runner(name: str) -> PipelineRunner:
    return PipelineRunner(PIPELINES / name)


def _write_pipeline(tmp_path: Path, yaml_text: str) -> Path:
    """Write an inline pipeline YAML plus the greet.j2 template to tmp_path."""
    pipeline_file = tmp_path / "pipeline.yaml"
    pipeline_file.write_text(yaml_text)
    (tmp_path / "greet.j2").write_text(GREET_J2)
    return pipeline_file


# ── No outputs block → nothing saved ──────────────────────────────────────────

class TestOutputsDisabled:
    def test_no_outputs_block_saves_nothing(self, tmp_path):
        runner = _runner("hello.yaml")
        runner.run({"name": "Ada", "output_dir": str(tmp_path)})
        assert list(tmp_path.iterdir()) == []

    def test_dry_run_saves_nothing(self, tmp_path):
        runner = _runner("outputs.yaml")
        runner.run({"name": "Ada", "output_dir": str(tmp_path)}, dry_run=True)
        assert list(tmp_path.iterdir()) == []


# ── Save-all default behaviour ─────────────────────────────────────────────────

class TestSaveAll:
    def test_all_steps_saved_by_default(self, tmp_path):
        runner = _runner("outputs.yaml")
        runner.run({"name": "Ada", "output_dir": str(tmp_path)})
        # step_a has no save key → saved as step_a.json
        assert (tmp_path / "step_a.json").exists()
        # step_b has save: false → not saved
        assert not (tmp_path / "step_b.json").exists()
        # step_c has save: custom/greeting.json
        assert (tmp_path / "custom" / "greeting.json").exists()

    def test_saved_file_is_valid_json(self, tmp_path):
        runner = _runner("outputs.yaml")
        runner.run({"name": "Ada", "output_dir": str(tmp_path)})
        data = json.loads((tmp_path / "step_a.json").read_text())
        assert data["message"] == "Bonjour Ada!"
        assert data["language"] == "French"

    def test_none_result_not_saved(self, tmp_path):
        """A step that is skipped (None result) should not produce a file."""
        yaml_text = """
models:
  default:
    provider: mock
    model: mock-model
    mock_responses:
      - '{"message": "hi", "language": "en"}'

outputs:
  dir: "{{ ctx.output_dir }}"

steps:
  - name: always_runs
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting

  - name: conditional
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting
    condition: "False"
"""
        pipeline_file = _write_pipeline(tmp_path, yaml_text)
        out_dir = tmp_path / "out"
        runner = PipelineRunner(pipeline_file)
        runner.run({"name": "Ada", "output_dir": str(out_dir)})
        assert (out_dir / "always_runs.json").exists()
        assert not (out_dir / "conditional.json").exists()


# ── final_as ───────────────────────────────────────────────────────────────────

class TestFinalAs:
    def test_final_as_saved(self, tmp_path):
        runner = _runner("outputs.yaml")
        runner.run({"name": "Ada", "output_dir": str(tmp_path)})
        assert (tmp_path / "result.json").exists()

    def test_final_as_contains_last_non_none_result(self, tmp_path):
        runner = _runner("outputs.yaml")
        runner.run({"name": "Ada", "output_dir": str(tmp_path)})
        # step_c is the last step with a result (step_b is save:false but still ran)
        data = json.loads((tmp_path / "result.json").read_text())
        assert data["message"] == "Bonjour Ada!"

    def test_final_as_falls_back_when_last_step_none(self, tmp_path):
        """If the last step is skipped, final_as gets the previous non-None result."""
        yaml_text = """
models:
  default:
    provider: mock
    model: mock-model
    mock_responses:
      - '{"message": "fallback", "language": "en"}'

outputs:
  dir: "{{ ctx.output_dir }}"
  final_as: final.json

steps:
  - name: first
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting

  - name: last
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting
    condition: "False"
"""
        pipeline_file = _write_pipeline(tmp_path, yaml_text)
        out_dir = tmp_path / "out"
        runner = PipelineRunner(pipeline_file)
        runner.run({"name": "Ada", "output_dir": str(out_dir)})
        data = json.loads((out_dir / "final.json").read_text())
        assert data["message"] == "fallback"

    def test_no_final_as_no_extra_file(self, tmp_path):
        yaml_text = """
models:
  default:
    provider: mock
    model: mock-model
    mock_responses:
      - '{"message": "hi", "language": "en"}'

outputs:
  dir: "{{ ctx.output_dir }}"

steps:
  - name: only_step
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting
"""
        pipeline_file = _write_pipeline(tmp_path, yaml_text)
        out_dir = tmp_path / "out"
        PipelineRunner(pipeline_file).run({"name": "Ada", "output_dir": str(out_dir)})
        files = {p.name for p in out_dir.iterdir()}
        assert files == {"only_step.json"}


# ── Default dir (no dir key) ───────────────────────────────────────────────────

class TestDefaultDir:
    def test_default_dir_is_outputs(self, tmp_path, monkeypatch):
        """When outputs.dir is omitted, files go to ./outputs/ relative to cwd."""
        monkeypatch.chdir(tmp_path)
        yaml_text = """
models:
  default:
    provider: mock
    model: mock-model
    mock_responses:
      - '{"message": "hi", "language": "en"}'

outputs:
  final_as: out.json

steps:
  - name: step
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting
"""
        pipeline_file = _write_pipeline(tmp_path, yaml_text)
        PipelineRunner(pipeline_file).run({"name": "Ada"})
        assert (tmp_path / "outputs" / "step.json").exists()
        assert (tmp_path / "outputs" / "out.json").exists()


# ── Ensemble sub-results ───────────────────────────────────────────────────────

class TestEnsembleOutputs:
    def test_ensemble_saves_merged_and_members(self, tmp_path):
        runner = _runner("outputs_ensemble.yaml")
        runner.run({"name": "Ada", "output_dir": str(tmp_path)})
        assert (tmp_path / "extract.json").exists()
        assert (tmp_path / "extract.primary.json").exists()
        assert (tmp_path / "extract.reviewer.json").exists()

    def test_ensemble_save_false_suppresses_all(self, tmp_path):
        yaml_text = """
models:
  primary:
    provider: mock
    model: mock-primary
    mock_responses:
      - '{"message": "hi", "language": "en"}'
  reviewer:
    provider: mock
    model: mock-reviewer
    mock_responses:
      - '{"message": "hi", "language": "en"}'
  judge_model:
    provider: mock
    model: mock-judge
    mock_responses:
      - '{"message": "hi", "language": "en"}'

outputs:
  dir: "{{ ctx.output_dir }}"

steps:
  - name: extract
    type: ensemble
    schema: tests.fixtures.schemas:Greeting
    prompt: greet.j2
    save: false
    members:
      - model: primary
        name: primary
      - model: reviewer
        name: reviewer
        required: false
    judge:
      model: judge_model
      condition: all_succeeded
"""
        pipeline_file = _write_pipeline(tmp_path, yaml_text)
        out_dir = tmp_path / "out"
        PipelineRunner(pipeline_file).run({"name": "Ada", "output_dir": str(out_dir)})
        assert not out_dir.exists() or list(out_dir.iterdir()) == []

    def test_ensemble_custom_save_overrides_merged_only(self, tmp_path):
        yaml_text = """
models:
  primary:
    provider: mock
    model: mock-primary
    mock_responses:
      - '{"message": "hi", "language": "en"}'
  reviewer:
    provider: mock
    model: mock-reviewer
    mock_responses:
      - '{"message": "hi", "language": "en"}'
  judge_model:
    provider: mock
    model: mock-judge
    mock_responses:
      - '{"message": "hi", "language": "en"}'

outputs:
  dir: "{{ ctx.output_dir }}"

steps:
  - name: extract
    type: ensemble
    schema: tests.fixtures.schemas:Greeting
    prompt: greet.j2
    save: merged.json
    members:
      - model: primary
        name: primary
      - model: reviewer
        name: reviewer
        required: false
    judge:
      model: judge_model
      condition: all_succeeded
"""
        pipeline_file = _write_pipeline(tmp_path, yaml_text)
        out_dir = tmp_path / "out"
        PipelineRunner(pipeline_file).run({"name": "Ada", "output_dir": str(out_dir)})
        assert (out_dir / "merged.json").exists()
        assert not (out_dir / "extract.json").exists()
        # sub-results not saved when save is explicitly set (non-UNSET)
        assert not (out_dir / "extract.primary.json").exists()


# ── Validation ─────────────────────────────────────────────────────────────────

class TestOutputsValidation:
    def test_invalid_outputs_type_raises(self, tmp_path):
        yaml_text = "steps: [{name: s, type: llm, model: m}]\noutputs: bad_string\n"
        p = tmp_path / "bad.yaml"
        p.write_text(yaml_text)
        with pytest.raises(PipelineLoadError, match="outputs"):
            PipelineRunner(p)

    def test_invalid_dir_type_raises(self, tmp_path):
        yaml_text = "steps: [{name: s, type: llm, model: m}]\noutputs:\n  dir: 123\n"
        p = tmp_path / "bad.yaml"
        p.write_text(yaml_text)
        with pytest.raises(PipelineLoadError, match="outputs.dir"):
            PipelineRunner(p)

    def test_invalid_final_as_type_raises(self, tmp_path):
        yaml_text = "steps: [{name: s, type: llm, model: m}]\noutputs:\n  final_as: [list]\n"
        p = tmp_path / "bad.yaml"
        p.write_text(yaml_text)
        with pytest.raises(PipelineLoadError, match="outputs.final_as"):
            PipelineRunner(p)

    def test_invalid_save_type_on_step_raises(self, tmp_path):
        yaml_text = """
models:
  default:
    provider: mock
    model: m
    mock_responses: ['{"message":"hi","language":"en"}']
steps:
  - name: s
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting
    save: 42
"""
        p = tmp_path / "bad.yaml"
        p.write_text(yaml_text)
        with pytest.raises(StepConfigError, match="save"):
            PipelineRunner(p)

    def test_save_true_raises(self, tmp_path):
        """save: true is not a valid value — would silently produce True.json."""
        yaml_text = """
models:
  default:
    provider: mock
    model: m
    mock_responses: ['{"message":"hi","language":"en"}']
steps:
  - name: s
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting
    save: true
"""
        p = tmp_path / "bad.yaml"
        p.write_text(yaml_text)
        with pytest.raises(StepConfigError, match="save"):
            PipelineRunner(p)


# ── Edge cases ─────────────────────────────────────────────────────────────────

class TestOutputsEdgeCases:
    def test_non_pydantic_value_serialised_as_json(self, tmp_path):
        """A transform step returning a plain string goes through json.dumps, not model_dump_json."""
        yaml_text = """
outputs:
  dir: "{{ ctx.output_dir }}"

steps:
  - name: data
    type: transform
    fn: tests.fixtures.steps:identity
    inputs:
      name: "Ada"
"""
        pipeline_file = _write_pipeline(tmp_path, yaml_text)
        out_dir = tmp_path / "out"
        PipelineRunner(pipeline_file).run({"output_dir": str(out_dir)})
        raw = (out_dir / "data.json").read_text()
        assert json.loads(raw) == "Ada"

    def test_path_traversal_via_save_is_rejected(self, tmp_path):
        """save: '../evil.json' must not write outside output_dir."""
        yaml_text = """
models:
  default:
    provider: mock
    model: mock-model
    mock_responses:
      - '{"message": "hi", "language": "en"}'

outputs:
  dir: "{{ ctx.output_dir }}"

steps:
  - name: s
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting
    save: "../evil.json"
"""
        pipeline_file = _write_pipeline(tmp_path, yaml_text)
        out_dir = tmp_path / "out"
        PipelineRunner(pipeline_file).run({"name": "Ada", "output_dir": str(out_dir)})
        assert not (tmp_path / "evil.json").exists()

    def test_outputs_not_saved_when_pipeline_fails(self, tmp_path):
        """When the pipeline aborts (on_error: raise), no outputs should be written."""
        yaml_text = """
models:
  default:
    provider: mock
    model: mock-model
    mock_responses:
      - "not valid json"

outputs:
  dir: "{{ ctx.output_dir }}"

steps:
  - name: will_fail
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting
    max_attempts: 1
    on_error: raise
"""
        pipeline_file = _write_pipeline(tmp_path, yaml_text)
        out_dir = tmp_path / "out"
        try:
            PipelineRunner(pipeline_file).run({"name": "Ada", "output_dir": str(out_dir)})
        except Exception:
            pass
        assert not out_dir.exists() or list(out_dir.iterdir()) == []

    def test_final_as_collision_with_step_name_raises(self, tmp_path):
        """final_as that matches a step's auto-generated name must raise at load time."""
        yaml_text = """
models:
  default:
    provider: mock
    model: m
    mock_responses: ['{"message":"hi","language":"en"}']

outputs:
  dir: "{{ ctx.output_dir }}"
  final_as: step_a.json

steps:
  - name: step_a
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting
"""
        p = tmp_path / "bad.yaml"
        p.write_text(yaml_text)
        with pytest.raises(PipelineLoadError, match="collides"):
            PipelineRunner(p)

    def test_final_as_returns_none_when_all_steps_skipped(self, tmp_path):
        """_resolve_final_result returns None when every step is conditioned away."""
        yaml_text = """
models:
  default:
    provider: mock
    model: mock-model
    mock_responses:
      - '{"message": "hi", "language": "en"}'

outputs:
  dir: "{{ ctx.output_dir }}"
  final_as: final.json

steps:
  - name: never
    type: llm
    model: default
    prompt: greet.j2
    schema: tests.fixtures.schemas:Greeting
    condition: "False"
"""
        pipeline_file = _write_pipeline(tmp_path, yaml_text)
        out_dir = tmp_path / "out"
        PipelineRunner(pipeline_file).run({"name": "Ada", "output_dir": str(out_dir)})
        # final_as should not be written when there is nothing to write
        assert not (out_dir / "final.json").exists()
