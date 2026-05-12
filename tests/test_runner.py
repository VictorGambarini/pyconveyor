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


# ── schema: {$ref: ...} ──────────────────────────────────────────────────────

class TestSchemaRefFiles:
    def test_llm_schema_ref_yaml_file(self, tmp_path: Path):
        (tmp_path / "schemas").mkdir()
        (tmp_path / "schemas" / "greeting.yaml").write_text(
            "message: str\nlanguage: str\n",
            encoding="utf-8",
        )
        (tmp_path / "p.j2").write_text("say hi", encoding="utf-8")
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"message": "Bonjour Ada!", "language": "French"}\'\n'
            "steps:\n"
            "  - name: greet\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt: p.j2\n"
            "    schema:\n"
            "      $ref: schemas/greeting.yaml\n",
            encoding="utf-8",
        )

        rctx = PipelineRunner(pipeline).run({})
        assert not rctx.failed
        assert rctx.steps["greet"].value.message == "Bonjour Ada!"

    def test_llm_schema_ref_json_file(self, tmp_path: Path):
        (tmp_path / "schemas").mkdir()
        (tmp_path / "schemas" / "greeting.json").write_text(
            '{"message": "str", "language": "str"}',
            encoding="utf-8",
        )
        (tmp_path / "p.j2").write_text("say hi", encoding="utf-8")
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"message": "Bonjour Ada!", "language": "French"}\'\n'
            "steps:\n"
            "  - name: greet\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt: p.j2\n"
            "    schema:\n"
            "      $ref: schemas/greeting.json\n",
            encoding="utf-8",
        )

        rctx = PipelineRunner(pipeline).run({})
        assert not rctx.failed
        assert rctx.steps["greet"].value.language == "French"


# ── http step ────────────────────────────────────────────────────────────────

class TestHttpStep:
    def test_http_step_parses_json(self, tmp_path: Path, monkeypatch):
        import httpx

        calls: list[dict] = []

        def _fake_request(**kwargs):
            calls.append(kwargs)
            return httpx.Response(
                status_code=200,
                json={"ok": True, "token": "abc"},
                request=httpx.Request("GET", kwargs["url"]),
            )

        monkeypatch.setattr(httpx, "request", _fake_request)

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "steps:\n"
            "  - name: fetch\n"
            "    type: http\n"
            "    url: \"{{ ctx.url }}\"\n"
            "    headers:\n"
            "      Authorization: \"Bearer {{ env.API_TOKEN }}\"\n"
            "    params:\n"
            "      q: \"{{ ctx.query }}\"\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("API_TOKEN", "secret-123")
        rctx = PipelineRunner(pipeline).run({"url": "https://example.com", "query": "paper"})
        assert not rctx.failed
        assert rctx.steps["fetch"].value == {"ok": True, "token": "abc"}
        assert calls[0]["headers"]["Authorization"] == "Bearer secret-123"
        assert calls[0]["params"]["q"] == "paper"

    def test_http_step_retries_on_5xx(self, tmp_path: Path, monkeypatch):
        import httpx

        count = {"n": 0}

        def _fake_request(**kwargs):
            count["n"] += 1
            if count["n"] == 1:
                return httpx.Response(
                    status_code=503,
                    text="temporary",
                    request=httpx.Request("GET", kwargs["url"]),
                )
            return httpx.Response(
                status_code=200,
                json={"ok": True},
                request=httpx.Request("GET", kwargs["url"]),
            )

        monkeypatch.setattr(httpx, "request", _fake_request)

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "steps:\n"
            "  - name: fetch\n"
            "    type: http\n"
            "    url: https://example.com\n"
            "    retries: 2\n"
            "    backoff_seconds: 0\n",
            encoding="utf-8",
        )

        rctx = PipelineRunner(pipeline).run({})
        assert not rctx.failed
        assert count["n"] == 2

    def test_http_step_respects_expected_status(self, tmp_path: Path, monkeypatch):
        import httpx

        def _fake_request(**kwargs):
            return httpx.Response(
                status_code=409,
                json={"status": "already_exists"},
                request=httpx.Request("POST", kwargs["url"]),
            )

        monkeypatch.setattr(httpx, "request", _fake_request)

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "steps:\n"
            "  - name: upsert\n"
            "    type: http\n"
            "    method: POST\n"
            "    url: https://example.com\n"
            "    expected_status: [200, 201, 409]\n",
            encoding="utf-8",
        )

        rctx = PipelineRunner(pipeline).run({})
        assert not rctx.failed
        assert rctx.steps["upsert"].value["status"] == "already_exists"

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


# ── Parallel step failure handling ───────────────────────────────────────────

class TestParallelStepFailures:
    def test_required_child_failure_raises(self, tmp_path: Path):
        """If a required child fails, the parallel step raises RuntimeError."""
        (tmp_path / "bad.j2").write_text("{{ undefined_var }}")
        pipeline = tmp_path / "par_fail.yaml"
        pipeline.write_text(
            "models:\n"
            "  m:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            "      - '{\"message\": \"hi\", \"language\": \"en\"}'\n"
            "steps:\n"
            "  - name: par\n"
            "    type: parallel\n"
            "    steps:\n"
            "      - name: child_ok\n"
            "        type: llm\n"
            "        model: m\n"
            "        prompt: bad.j2\n"
            "        schema: tests.fixtures.schemas:Greeting\n"
            "        max_attempts: 1\n"
            "        required: true\n"
        )
        rctx = PipelineRunner(pipeline).run({})
        assert rctx.failed

    def test_optional_child_failure_continues(self, tmp_path: Path):
        """If an optional child (required=false) fails, the result is None."""
        (tmp_path / "bad.j2").write_text("{{ undefined_var }}")
        (tmp_path / "good.j2").write_text("Hello!")
        pipeline = tmp_path / "par_opt.yaml"
        pipeline.write_text(
            "models:\n"
            "  m:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            "      - '{\"message\": \"hi\", \"language\": \"en\"}'\n"
            "steps:\n"
            "  - name: par\n"
            "    type: parallel\n"
            "    on_error: continue\n"
            "    steps:\n"
            "      - name: child_fail\n"
            "        type: llm\n"
            "        model: m\n"
            "        prompt: bad.j2\n"
            "        max_attempts: 1\n"
            "        required: false\n"
            "      - name: child_ok\n"
            "        type: llm\n"
            "        model: m\n"
            "        prompt: good.j2\n"
            "        max_attempts: 1\n"
            "        required: true\n"
        )
        rctx = PipelineRunner(pipeline).run({})
        # Optional child failed → result is None; required child succeeded
        par_result = rctx.steps["par"].value
        assert par_result is not None
        assert par_result.get("child_fail") is None


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


# ── Lifecycle hooks ────────────────────────────────────────────────────────────

class TestLifecycleHooks:
    def test_on_run_start_called(self):
        seen: list[dict] = []
        runner = _runner("hello.yaml")
        runner.on_run_start(lambda data: seen.append(data))
        runner.run({"name": "Ada"})
        assert seen == [{"name": "Ada"}]

    def test_on_run_end_called(self):
        seen = []
        runner = _runner("hello.yaml")
        runner.on_run_end(lambda rctx: seen.append(rctx.failed))
        runner.run({"name": "Ada"})
        assert seen == [False]

    def test_on_run_start_hook_error_does_not_abort(self):
        runner = _runner("hello.yaml")
        runner.on_run_start(lambda data: (_ for _ in ()).throw(RuntimeError("hook error")))
        rctx = runner.run({"name": "Ada"})
        assert not rctx.failed

    def test_on_run_end_hook_error_does_not_abort(self):
        runner = _runner("hello.yaml")
        runner.on_run_end(lambda rctx: (_ for _ in ()).throw(RuntimeError("end hook error")))
        rctx = runner.run({"name": "Ada"})
        assert not rctx.failed

    def test_multiple_run_start_hooks(self):
        calls: list[str] = []
        runner = _runner("hello.yaml")
        runner.on_run_start(lambda d: calls.append("first"))
        runner.on_run_start(lambda d: calls.append("second"))
        runner.run({"name": "Ada"})
        assert calls == ["first", "second"]

    def test_multiple_run_end_hooks(self):
        calls: list[str] = []
        runner = _runner("hello.yaml")
        runner.on_run_end(lambda r: calls.append("first"))
        runner.on_run_end(lambda r: calls.append("second"))
        runner.run({"name": "Ada"})
        assert calls == ["first", "second"]

    def test_on_run_start_decorator_returns_fn(self):
        runner = _runner("hello.yaml")

        @runner.on_run_start
        def my_hook(data: dict) -> None:
            pass

        assert my_hook is not None

    def test_on_run_end_decorator_returns_fn(self):
        runner = _runner("hello.yaml")

        @runner.on_run_end
        def my_hook(rctx: RunContext) -> None:
            pass

        assert my_hook is not None

    def test_on_llm_call_fired_per_attempt(self):
        calls: list[tuple] = []
        runner = _runner("hello.yaml")
        runner.on_llm_call(lambda step, model, response: calls.append((step, model, response)))
        runner.run({"name": "Ada"})
        assert len(calls) == 1
        step_name, model, response = calls[0]
        assert step_name == "greet"
        assert isinstance(response, str)

    def test_on_llm_call_hook_error_does_not_abort(self):
        runner = _runner("hello.yaml")
        runner.on_llm_call(lambda s, m, r: (_ for _ in ()).throw(RuntimeError("llm hook error")))
        rctx = runner.run({"name": "Ada"})
        assert not rctx.failed

    def test_on_run_end_called_when_pipeline_fails(self):
        # Regression: on_run_end must fire even when pipeline aborts
        seen = []
        runner = _runner("hello.yaml")
        runner.on_run_end(lambda rctx: seen.append(rctx.failed))
        from unittest.mock import patch
        with patch("pyconveyor.runner.execute_llm_step", side_effect=RuntimeError("forced")):
            rctx = runner.run({"name": "Ada"})
        assert rctx.failed
        assert seen == [True]  # on_run_end fired with the failed rctx

    def test_on_step_end_hook_error_does_not_abort(self):
        runner = _runner("hello.yaml")
        runner.on_step_end(lambda name, val, rctx: (_ for _ in ()).throw(RuntimeError("step hook error")))
        rctx = runner.run({"name": "Ada"})
        assert not rctx.failed


# ── Feature 1: Inline YAML schemas ───────────────────────────────────────────

class TestInlineYamlSchema:
    def _inline_pipeline(self, tmp_path: Path, schema_block: str, extra_step: str = "") -> Path:
        (tmp_path / "p.j2").write_text("Extract info.")
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"title": "Hello", "score": null}\'\n'
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt: p.j2\n"
            f"    schema:\n{schema_block}\n"
            + extra_step
        )
        return pipeline

    def test_inline_dict_schema_loads(self, tmp_path: Path):
        pipeline = self._inline_pipeline(
            tmp_path,
            "      title: str\n      score: int | None",
        )
        runner = PipelineRunner(pipeline)
        assert runner is not None

    def test_schema_cls_is_basemodel(self, tmp_path: Path):
        from pydantic import BaseModel
        pipeline = self._inline_pipeline(
            tmp_path,
            "      title: str\n      score: int | None",
        )
        runner = PipelineRunner(pipeline)
        schema_cls = runner._spec["steps"][0]["_schema_cls"]
        assert issubclass(schema_cls, BaseModel)

    def test_valid_dict_instantiates(self, tmp_path: Path):
        pipeline = self._inline_pipeline(
            tmp_path,
            "      title: str\n      score: int | None",
        )
        runner = PipelineRunner(pipeline)
        schema_cls = runner._spec["steps"][0]["_schema_cls"]
        m = schema_cls(title="hi", score=None)
        assert m.title == "hi"

    def test_invalid_dict_raises_validation_error(self, tmp_path: Path):
        from pydantic import ValidationError
        pipeline = self._inline_pipeline(
            tmp_path,
            "      title: str",
        )
        runner = PipelineRunner(pipeline)
        schema_cls = runner._spec["steps"][0]["_schema_cls"]
        with pytest.raises(ValidationError):
            schema_cls()

    def test_unsupported_type_raises_schema_ref_error_at_load(self, tmp_path: Path):
        from pyconveyor.errors import SchemaRefError
        (tmp_path / "p.j2").write_text("Extract.")
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
            "    prompt: p.j2\n"
            "    schema:\n"
            "      ts: datetime\n"
        )
        with pytest.raises(SchemaRefError):
            PipelineRunner(pipeline)

    def test_inline_schema_run_succeeds(self, tmp_path: Path):
        (tmp_path / "p.j2").write_text("Extract.")
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"title": "My Title", "score": 42}\'\n'
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt: p.j2\n"
            "    schema:\n"
            "      title: str\n"
            "      score: int\n"
        )
        rctx = PipelineRunner(pipeline).run({})
        assert not rctx.failed
        assert rctx.steps["extract"].value.title == "My Title"


# ── Feature 2: schemas= kwarg ─────────────────────────────────────────────────

class TestSchemasKwarg:
    def _simple_pipeline(self, tmp_path: Path) -> Path:
        (tmp_path / "p.j2").write_text("Extract.")
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"title": "Hello", "score": 5}\'\n'
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt: p.j2\n"
        )
        return pipeline

    def test_schema_override_sets_schema_cls(self, tmp_path: Path):
        from pydantic import BaseModel

        class MyModel(BaseModel):
            title: str
            score: int

        pipeline = self._simple_pipeline(tmp_path)
        runner = PipelineRunner(pipeline, schemas={"extract": MyModel})
        assert runner._spec["steps"][0]["_schema_cls"] is MyModel

    def test_run_returns_mymodel_instance(self, tmp_path: Path):
        from pydantic import BaseModel

        class MyModel(BaseModel):
            title: str
            score: int

        pipeline = self._simple_pipeline(tmp_path)
        runner = PipelineRunner(pipeline, schemas={"extract": MyModel})
        rctx = runner.run({})
        assert not rctx.failed
        assert isinstance(rctx.steps["extract"].value, MyModel)

    def test_non_basemodel_raises_schema_ref_error(self, tmp_path: Path):
        from pyconveyor.errors import SchemaRefError

        pipeline = self._simple_pipeline(tmp_path)
        with pytest.raises(SchemaRefError):
            PipelineRunner(pipeline, schemas={"extract": str})  # type: ignore[dict-item]

    def test_unknown_step_name_raises_step_config_error(self, tmp_path: Path):
        from pydantic import BaseModel

        from pyconveyor.errors import StepConfigError

        class MyModel(BaseModel):
            x: str

        pipeline = self._simple_pipeline(tmp_path)
        with pytest.raises(StepConfigError):
            PipelineRunner(pipeline, schemas={"nonexistent": MyModel})

    def test_schemas_none_changes_nothing(self, tmp_path: Path):
        pipeline = self._simple_pipeline(tmp_path)
        runner = PipelineRunner(pipeline, schemas=None)
        assert "_schema_cls" not in runner._spec["steps"][0]

    def test_kwarg_overrides_yaml_schema(self, tmp_path: Path):
        """schemas= kwarg wins over schema: in YAML."""
        from pydantic import BaseModel

        class Override(BaseModel):
            title: str
            score: int

        (tmp_path / "p.j2").write_text("Hello.")
        p = tmp_path / "pipeline.yaml"
        p.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"title": "Hi", "score": 1}\'\n'
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt: p.j2\n"
            "    schema:\n"
            "      title: str\n"
            "      score: int\n"
        )
        runner = PipelineRunner(p, schemas={"extract": Override})
        assert runner._spec["steps"][0]["_schema_cls"] is Override

    def test_batch_runner_accepts_schemas(self, tmp_path: Path):
        from pydantic import BaseModel

        from pyconveyor import BatchRunner

        class MyModel(BaseModel):
            title: str
            score: int

        pipeline = self._simple_pipeline(tmp_path)
        br = BatchRunner(pipeline, schemas={"extract": MyModel})
        assert br._runner._spec["steps"][0]["_schema_cls"] is MyModel


# ── Feature 4: schema_hint template variable ──────────────────────────────────

class TestSchemaHint:
    def test_schema_hint_non_empty_when_schema_present(self, tmp_path: Path):
        (tmp_path / "p.j2").write_text("{{ schema_hint }}")
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
            "    prompt: p.j2\n"
            "    schema:\n"
            "      title: str\n"
        )
        from unittest.mock import patch

        prompts: list[str] = []

        # call_llm(client, messages, model, ...) — prompt is in messages[-1]["content"]
        def fake_call_llm(client: object, messages: list, model: str, **kw: object) -> tuple:
            user_msg = next((m["content"] for m in messages if m.get("role") == "user"), "")
            prompts.append(user_msg)
            return '{"title": "Hi"}', None

        with patch("pyconveyor.steps.llm_step.call_llm", fake_call_llm):
            PipelineRunner(pipeline).run({})

        assert prompts
        assert "Return a JSON object" in prompts[0]

    def test_schema_hint_empty_when_no_schema(self, tmp_path: Path):
        (tmp_path / "p.j2").write_text("hint=[{{ schema_hint }}]")
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - "raw text"\n'
            "steps:\n"
            "  - name: step1\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt: p.j2\n"
        )
        from unittest.mock import patch

        prompts: list[str] = []

        def fake_call_llm(client: object, messages: list, model: str, **kw: object) -> tuple:
            user_msg = next((m["content"] for m in messages if m.get("role") == "user"), "")
            prompts.append(user_msg)
            return "raw text", None

        with patch("pyconveyor.steps.llm_step.call_llm", fake_call_llm):
            PipelineRunner(pipeline).run({})

        assert prompts
        assert "hint=[]" in prompts[0]

    def test_schema_hint_not_overwritten_when_in_resolved_inputs(self, tmp_path: Path):
        """User-provided schema_hint in template vars is preserved, not overwritten."""
        (tmp_path / "p.j2").write_text("hint=[{{ schema_hint }}]")
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
            "    prompt: p.j2\n"
            "    schema:\n"
            "      title: str\n"
            "    vars:\n"
            "      schema_hint: MY_CUSTOM_HINT\n"
        )
        from unittest.mock import patch

        prompts: list[str] = []

        def fake_call_llm(client: object, messages: list, model: str, **kw: object) -> tuple:
            user_msg = next((m["content"] for m in messages if m.get("role") == "user"), "")
            prompts.append(user_msg)
            return '{"title": "Hi"}', None

        with patch("pyconveyor.steps.llm_step.call_llm", fake_call_llm):
            PipelineRunner(pipeline).run({})

        assert prompts
        assert "MY_CUSTOM_HINT" in prompts[0]


# ── schemas= kwarg walking into parallel/condition children ───────────────────

class TestSchemasKwargChildWalking:
    def test_schemas_targets_parallel_child(self, tmp_path: Path):
        """schemas= kwarg applies to a step nested inside a parallel step."""
        from pydantic import BaseModel

        class ChildSchema(BaseModel):
            value: int

        (tmp_path / "p.j2").write_text("Extract.")
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"value": 1}\'\n'
            "steps:\n"
            "  - name: par\n"
            "    type: parallel\n"
            "    steps:\n"
            "      - name: child\n"
            "        type: llm\n"
            "        model: default\n"
            "        prompt: p.j2\n"
        )
        runner = PipelineRunner(pipeline, schemas={"child": ChildSchema})
        # Verify _schema_cls was injected into the child step
        child_step = runner._spec["steps"][0]["steps"][0]
        assert child_step["_schema_cls"] is ChildSchema

    def test_schemas_targets_condition_branch_step(self, tmp_path: Path):
        """schemas= kwarg applies to a step nested inside a condition's then branch."""
        from pydantic import BaseModel

        class BranchSchema(BaseModel):
            result: str

        (tmp_path / "p.j2").write_text("Extract.")
        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            '      - \'{"result": "ok"}\'\n'
            "steps:\n"
            "  - name: gate\n"
            "    type: condition\n"
            "    condition: \"True\"\n"
            "    then:\n"
            "      - name: branch_step\n"
            "        type: llm\n"
            "        model: default\n"
            "        prompt: p.j2\n"
        )
        runner = PipelineRunner(pipeline, schemas={"branch_step": BranchSchema})
        # Verify _schema_cls was injected into the then-branch step
        then_steps = runner._spec["steps"][0]["then"]
        assert then_steps[0]["_schema_cls"] is BranchSchema
