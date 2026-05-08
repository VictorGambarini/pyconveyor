"""Tests for PipelineRunner and RunContext."""
from __future__ import annotations

from pathlib import Path

import pytest

from pyconveyor import PipelineRunner, RunContext
from pyconveyor.errors import PipelineLoadError

PIPELINES = Path(__file__).parent / "fixtures" / "pipelines"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _runner(name: str) -> PipelineRunner:
    return PipelineRunner(PIPELINES / name)


# ── Load validation ────────────────────────────────────────────────────────────

class TestPipelineLoad:
    def test_valid_pipeline_loads(self):
        r = _runner("hello.yaml")
        assert r is not None

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(PipelineLoadError):
            PipelineRunner(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("steps: [bad: ][")
        with pytest.raises(PipelineLoadError):
            PipelineRunner(bad)


# ── Basic LLM step (mock provider) ────────────────────────────────────────────

class TestLlmStepMock:
    def test_single_step_success(self):
        rctx = _runner("hello.yaml").run({"name": "Ada", "language": "French"})
        assert not rctx.failed
        assert "greet" in rctx.steps
        sr = rctx.steps["greet"]
        assert sr.status == "success"

    def test_result_has_pydantic_model(self):
        from tests.fixtures.schemas import Greeting
        rctx = _runner("hello.yaml").run({"name": "Ada", "language": "French"})
        sr = rctx.steps["greet"]
        assert isinstance(sr.value, Greeting)
        assert sr.value.message == "Bonjour Ada!"

    def test_attribute_proxy(self):
        rctx = _runner("hello.yaml").run({"name": "Ada", "language": "French"})
        sr = rctx.steps["greet"]
        # Proxy access to inner model
        assert sr.message == "Bonjour Ada!"
        assert sr.language == "French"

    def test_run_summary(self):
        rctx = _runner("hello.yaml").run({"name": "Ada"})
        s = rctx.summary()
        assert "greet" in s.steps_run
        assert s.steps_failed == []
        assert s.elapsed_seconds >= 0

    def test_attempt_log_on_success(self):
        rctx = _runner("hello.yaml").run({"name": "Ada"})
        sr = rctx.steps["greet"]
        assert sr.last_attempt is not None
        assert sr.last_attempt.status == "success"


# ── Retry and feedback loop (§10) ─────────────────────────────────────────────

class TestRetryFeedback:
    def test_retries_on_bad_json_then_succeeds(self):
        """Mock: bad JSON → schema-invalid → valid — should succeed on 3rd attempt."""
        rctx = _runner("retry_feedback.yaml").run({"name": "Ada"})
        assert not rctx.failed
        sr = rctx.steps["greet"]
        assert sr.status == "success"

    def test_attempt_count_correct(self):
        rctx = _runner("retry_feedback.yaml").run({"name": "Ada"})
        sr = rctx.steps["greet"]
        assert len(sr.attempts) == 3  # 2 failures + 1 success

    def test_first_two_attempts_failed(self):
        rctx = _runner("retry_feedback.yaml").run({"name": "Ada"})
        sr = rctx.steps["greet"]
        assert sr.attempts[0].status in ("parse_error", "schema_error", "failed", "error")
        assert sr.attempts[1].status in ("parse_error", "schema_error", "failed", "error")
        assert sr.attempts[2].status == "success"


# ── on_error: continue ────────────────────────────────────────────────────────

class TestOnErrorContinue:
    def test_pipeline_completes_despite_failure(self):
        rctx = _runner("on_error_continue.yaml").run({})
        # The first step should have failed but the pipeline continues
        assert not rctx.failed

    def test_failed_step_has_status_failed(self):
        rctx = _runner("on_error_continue.yaml").run({})
        assert rctx.steps["optional"].status == "failed"

    def test_next_step_runs(self):
        rctx = _runner("on_error_continue.yaml").run({})
        assert rctx.steps["fallback"].status == "success"
        assert rctx.steps["fallback"].value == "fallback_value"


# ── on_error: skip_remaining ─────────────────────────────────────────────────

class TestSkipRemaining:
    def test_remaining_steps_are_skipped(self):
        rctx = _runner("skip_remaining.yaml").run({})
        # Pipeline shouldn't raise but fail_step should fail
        # should_be_skipped should be skipped
        assert rctx.steps["should_be_skipped"].status == "skipped"

    def test_failed_step_recorded(self):
        rctx = _runner("skip_remaining.yaml").run({})
        assert rctx.steps["fail_step"].status == "failed"


# ── on_error: raise (default) ────────────────────────────────────────────────

class TestOnErrorRaise:
    def test_pipeline_aborts_on_failure(self, tmp_path):
        """Pipeline with default on_error (raise) should abort and set failed=True."""
        pipeline = tmp_path / "abort.yaml"
        pipeline.write_text(
            'models:\n'
            '  default:\n'
            '    provider: mock\n'
            '    model: mock-model\n'
            '    mock_responses:\n'
            '      - "not json"\n'
            'steps:\n'
            '  - name: fail\n'
            '    type: llm\n'
            '    model: default\n'
            '    prompt: greet.j2\n'
            '    schema: tests.fixtures.schemas:Greeting\n'
            '    max_attempts: 1\n'
            '    on_error: raise\n'
        )
        # Need a prompt file next to the pipeline
        (tmp_path / "greet.j2").write_text("Greet {{ ctx.name }}.")
        rctx = PipelineRunner(pipeline).run({"name": "Test"})
        assert rctx.failed
        assert rctx.failure_state is not None


# ── Parallel steps ────────────────────────────────────────────────────────────

class TestParallelStep:
    def test_parallel_children_run(self):
        rctx = _runner("parallel.yaml").run({"name": "Ada"})
        assert not rctx.failed
        sr = rctx.steps["extract"]
        assert sr.status == "success"
        assert isinstance(sr.value, dict)

    def test_parallel_result_contains_children(self):
        rctx = _runner("parallel.yaml").run({"name": "Ada"})
        result = rctx.steps["extract"].value
        assert "primary" in result
        assert "reviewer" in result

    def test_child_results_in_rctx(self):
        rctx = _runner("parallel.yaml").run({"name": "Ada"})
        # Children are also stored in rctx.steps
        assert "primary" in rctx.steps
        assert "reviewer" in rctx.steps


# ── Condition step ────────────────────────────────────────────────────────────

class TestConditionStep:
    def test_then_branch_when_true(self):
        rctx = _runner("condition.yaml").run({"should_greet": True, "name": "Ada"})
        assert not rctx.failed
        # 'greet' step from then-branch should have run
        assert "greet" in rctx.steps
        assert rctx.steps["greet"].status == "success"

    def test_else_branch_when_false(self):
        rctx = _runner("condition.yaml").run({"should_greet": False, "name": "Ada"})
        assert not rctx.failed
        assert "skip_msg" in rctx.steps
        assert rctx.steps["skip_msg"].value == "skipped"


# ── Model overrides ───────────────────────────────────────────────────────────

class TestModelOverrides:
    def test_override_mock_responses(self):
        """Pass model_overrides to change mock responses at run time."""
        rctx = _runner("hello.yaml").run(
            {"name": "Ada"},
            model_overrides={
                "default": {
                    "mock_responses": ['{"message": "Hey Ada!", "language": "English"}']
                }
            },
        )
        assert not rctx.failed
        assert rctx.steps["greet"].value.message == "Hey Ada!"


# ── on_step_end hook ─────────────────────────────────────────────────────────

class TestOnStepEndHook:
    def test_hook_called(self):
        called = []
        runner = _runner("hello.yaml")
        runner.on_step_end(lambda name, value, rctx: called.append(name))
        runner.run({"name": "Ada"})
        assert "greet" in called

    def test_hook_receives_value(self):
        values = []
        runner = _runner("hello.yaml")
        runner.on_step_end(lambda name, value, rctx: values.append(value))
        runner.run({"name": "Ada"})
        from tests.fixtures.schemas import Greeting
        assert isinstance(values[0], Greeting)


# ── RunContext step proxy ─────────────────────────────────────────────────────

class TestRunContextProxy:
    def test_step_dict_access(self):
        rctx = _runner("hello.yaml").run({"name": "Ada"})
        sr = rctx.steps["greet"]
        assert sr is not None

    def test_step_missing_key_returns_none(self):
        rctx = RunContext({"x": 1})
        from pyconveyor.runner import StepResult
        rctx._step_results["s"] = StepResult(name="s", value=None, status="success")
        assert rctx.steps["s"].nonexistent_attr is None
