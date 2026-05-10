"""Tests for type: ensemble step."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyconveyor import PipelineRunner
from pyconveyor.errors import ModelRefError, StepConfigError

PIPELINES = Path(__file__).parent / "fixtures" / "pipelines"


def _runner(name: str) -> PipelineRunner:
    return PipelineRunner(PIPELINES / name)


# ── Load validation ────────────────────────────────────────────────────────────


class TestEnsembleLoad:
    def test_valid_ensemble_loads(self):
        r = _runner("ensemble.yaml")
        assert r is not None

    def test_missing_members_raises(self, tmp_path):
        (tmp_path / "bad.yaml").write_text(
            "models:\n  m:\n    provider: mock\n    model: x\n"
            "steps:\n  - name: e\n    type: ensemble\n    members: []\n"
        )
        with pytest.raises(StepConfigError, match="at least one member"):
            PipelineRunner(tmp_path / "bad.yaml")

    def test_member_missing_model_raises(self, tmp_path):
        (tmp_path / "bad.yaml").write_text(
            "models:\n  m:\n    provider: mock\n    model: x\n"
            "steps:\n  - name: e\n    type: ensemble\n    members:\n      - required: false\n"
        )
        with pytest.raises(StepConfigError, match="missing required field 'model'"):
            PipelineRunner(tmp_path / "bad.yaml")

    def test_bad_model_ref_raises(self, tmp_path):
        (tmp_path / "bad.yaml").write_text(
            "models:\n  m:\n    provider: mock\n    model: x\n"
            "steps:\n  - name: e\n    type: ensemble\n    members:\n      - model: unknown\n"
        )
        with pytest.raises(ModelRefError):
            PipelineRunner(tmp_path / "bad.yaml")

    def test_bad_judge_model_ref_raises(self, tmp_path):
        (tmp_path / "bad.yaml").write_text(
            "models:\n  m:\n    provider: mock\n    model: x\n"
            "steps:\n  - name: e\n    type: ensemble\n    members:\n      - model: m\n"
            "    judge:\n      model: ghost\n"
        )
        with pytest.raises(ModelRefError, match="judge model"):
            PipelineRunner(tmp_path / "bad.yaml")

    def test_bad_judge_condition_raises(self, tmp_path):
        (tmp_path / "bad.yaml").write_text(
            "models:\n  m:\n    provider: mock\n    model: x\n"
            "steps:\n  - name: e\n    type: ensemble\n    members:\n      - model: m\n"
            "    judge:\n      model: m\n      condition: never\n"
        )
        with pytest.raises(StepConfigError, match="judge.condition"):
            PipelineRunner(tmp_path / "bad.yaml")


# ── Happy path ────────────────────────────────────────────────────────────────


class TestEnsembleRun:
    def test_both_succeed_judge_runs(self):
        rctx = _runner("ensemble.yaml").run({"name": "Ada", "language": "French"})
        assert not rctx.failed
        sr = rctx.steps["extract"]
        assert sr.status == "success"
        assert sr.value is not None

    def test_result_is_pydantic_model(self):
        from tests.fixtures.schemas import Greeting

        rctx = _runner("ensemble.yaml").run({"name": "Ada", "language": "French"})
        assert isinstance(rctx.steps["extract"].value, Greeting)

    def test_member_results_accessible(self):
        rctx = _runner("ensemble.yaml").run({"name": "Ada", "language": "French"})
        assert "extract.primary" in rctx.steps
        assert "extract.reviewer" in rctx.steps
        assert rctx.steps["extract.primary"].status == "success"
        assert rctx.steps["extract.reviewer"].status == "success"

    def test_attempt_logs_include_all_members(self):
        rctx = _runner("ensemble.yaml").run({"name": "Ada", "language": "French"})
        sr = rctx.steps["extract"]
        # Logs from 2 members + 1 judge = at least 3 entries
        assert len(sr.attempts) >= 3

    def test_no_judge_returns_first_member(self):
        rctx = _runner("ensemble_no_judge.yaml").run({"name": "Ada", "language": "French"})
        assert not rctx.failed
        sr = rctx.steps["extract"]
        assert sr.status == "success"
        # primary is listed first → its output is returned
        assert sr.value.message == "Hola!"

    def test_downstream_step_sees_ensemble_result(self, tmp_path):
        """Ensemble result is accessible via steps.extract in downstream expressions."""
        import yaml

        spec = {
            "models": {
                "m": {
                    "provider": "mock",
                    "model": "x",
                    "mock_responses": ['{"message": "Hi!", "language": "EN"}'],
                },
                "m2": {
                    "provider": "mock",
                    "model": "x2",
                    "mock_responses": ['{"message": "Hi!", "language": "EN"}', '{"result": "ok"}'],
                },
            },
            "steps": [
                {
                    "name": "extract",
                    "type": "ensemble",
                    "schema": "tests.fixtures.schemas:Greeting",
                    "members": [{"model": "m"}],
                },
                {
                    "name": "verify",
                    "type": "llm",
                    "model": "m2",
                    "vars": {"msg": "{{ steps.extract.message }}"},
                },
            ],
        }
        p = tmp_path / "inline.yaml"
        p.write_text(yaml.dump(spec))
        rctx = PipelineRunner(p).run({"name": "Ada"})
        assert not rctx.failed
        assert rctx.steps["verify"].status == "success"


# ── Fallback behaviour ─────────────────────────────────────────────────────────


class TestEnsembleFallback:
    def test_optional_member_fails_judge_skipped_fallback(self):
        """When optional member fails, only 1 member succeeded → judge not run."""
        rctx = _runner("ensemble_optional_fail.yaml").run({"name": "Ada", "language": "EN"})
        assert not rctx.failed
        sr = rctx.steps["extract"]
        assert sr.status == "success"
        assert sr.value.message == "Hello!"

    def test_optional_member_failure_recorded_in_logs(self):
        rctx = _runner("ensemble_optional_fail.yaml").run({"name": "Ada", "language": "EN"})
        sr = rctx.steps["extract"]
        failed_logs = [a for a in sr.attempts if a.status == "error"]
        assert failed_logs, "Expected at least one error log for the failed optional member"

    def test_required_member_fail_aborts_pipeline(self, tmp_path):
        import yaml

        spec = {
            "models": {
                "bad": {"provider": "mock", "model": "x", "mock_responses": ["not json"]},
            },
            "steps": [
                {
                    "name": "extract",
                    "type": "ensemble",
                    "schema": "tests.fixtures.schemas:Greeting",
                    "members": [{"model": "bad", "max_attempts": 1}],
                },
            ],
        }
        p = tmp_path / "fail.yaml"
        p.write_text(yaml.dump(spec))
        rctx = PipelineRunner(p).run({})
        assert rctx.failed

    def test_judge_fallback_on_judge_failure(self, tmp_path):
        """Judge failure → falls back to best member result without aborting."""
        import yaml

        spec = {
            "models": {
                "m": {
                    "provider": "mock",
                    "model": "x",
                    "mock_responses": [
                        '{"message": "A", "language": "EN"}',
                        '{"message": "B", "language": "EN"}',
                    ],
                },
                "judge": {
                    "provider": "mock",
                    "model": "j",
                    "mock_responses": ["totally invalid {{{"],
                },
            },
            "steps": [
                {
                    "name": "extract",
                    "type": "ensemble",
                    "schema": "tests.fixtures.schemas:Greeting",
                    "members": [
                        {"model": "m"},
                        {"model": "m"},
                    ],
                    "judge": {"model": "judge", "condition": "all_succeeded"},
                },
            ],
        }
        p = tmp_path / "judge_fail.yaml"
        p.write_text(yaml.dump(spec))
        rctx = PipelineRunner(p).run({})
        # Pipeline should not fail — falls back to first member
        assert not rctx.failed
        assert rctx.steps["extract"].value is not None


# ── Coverage gap tests ────────────────────────────────────────────────────────


class TestEnsembleCoverageGaps:
    def test_per_member_prompt_override(self, tmp_path):
        """G1: per-member prompt field overrides the step-level prompt."""
        import yaml

        (tmp_path / "base.j2").write_text("Base prompt for {{ ctx.name }}")
        (tmp_path / "override.j2").write_text("Override prompt")
        spec = {
            "models": {
                "m1": {
                    "provider": "mock",
                    "model": "x1",
                    "mock_responses": ['{"message": "Hi!", "language": "EN"}'],
                },
                "m2": {
                    "provider": "mock",
                    "model": "x2",
                    "mock_responses": ['{"message": "Hey!", "language": "EN"}'],
                },
            },
            "steps": [
                {
                    "name": "extract",
                    "type": "ensemble",
                    "schema": "tests.fixtures.schemas:Greeting",
                    "prompt": "base.j2",
                    "members": [
                        {"model": "m1"},
                        {"model": "m2", "prompt": "override.j2"},
                    ],
                },
            ],
        }
        p = tmp_path / "inline.yaml"
        p.write_text(yaml.dump(spec))
        rctx = PipelineRunner(p).run({"name": "Ada"})
        assert not rctx.failed
        assert rctx.steps["extract"].status == "success"

    def test_all_optional_members_fail_returns_none(self, tmp_path):
        """G2: all members are optional and all fail → ensemble returns None."""
        import yaml

        spec = {
            "models": {
                "bad": {"provider": "mock", "model": "x", "mock_responses": ["not json"]},
            },
            "steps": [
                {
                    "name": "extract",
                    "type": "ensemble",
                    "schema": "tests.fixtures.schemas:Greeting",
                    "members": [
                        {"model": "bad", "required": False, "max_attempts": 1},
                        {"model": "bad", "required": False, "max_attempts": 1},
                    ],
                },
            ],
        }
        p = tmp_path / "all_optional_fail.yaml"
        p.write_text(yaml.dump(spec))
        rctx = PipelineRunner(p).run({})
        assert not rctx.failed
        assert rctx.steps["extract"].value is None

    def test_judge_condition_any_succeeded(self, tmp_path):
        """G3: judge runs with any_succeeded even when a required member failed.

        With all_succeeded the judge would be skipped (bad is required and fails).
        With any_succeeded the judge runs as long as ≥2 members succeeded.
        Setup: good1 (required), good2 (optional), bad (required) → 2 succeed.
        """
        import yaml

        spec = {
            "models": {
                "good1": {
                    "provider": "mock",
                    "model": "x1",
                    "mock_responses": ['{"message": "Hi!", "language": "EN"}'],
                },
                "good2": {
                    "provider": "mock",
                    "model": "x2",
                    "mock_responses": ['{"message": "Hey!", "language": "EN"}'],
                },
                "bad": {"provider": "mock", "model": "y", "mock_responses": ["not json"]},
                "judge": {
                    "provider": "mock",
                    "model": "j",
                    "mock_responses": ['{"message": "Judged!", "language": "EN"}'],
                },
            },
            "steps": [
                {
                    "name": "extract",
                    "type": "ensemble",
                    "schema": "tests.fixtures.schemas:Greeting",
                    "members": [
                        {"model": "good1"},
                        {"model": "good2", "required": False},
                        {"model": "bad", "required": False, "max_attempts": 1},
                    ],
                    "judge": {"model": "judge", "condition": "any_succeeded"},
                },
            ],
        }
        p = tmp_path / "any_succeeded.yaml"
        p.write_text(yaml.dump(spec))
        rctx = PipelineRunner(p).run({})
        assert not rctx.failed
        assert rctx.steps["extract"].value.message == "Judged!"

    def test_explicit_judge_prompt(self, tmp_path):
        """G4: judge.prompt specified → used directly instead of auto-composed."""
        import yaml

        (tmp_path / "judge.j2").write_text("Judge prompt: pick the best answer.")
        spec = {
            "models": {
                "m1": {
                    "provider": "mock",
                    "model": "x1",
                    "mock_responses": ['{"message": "A", "language": "EN"}'],
                },
                "m2": {
                    "provider": "mock",
                    "model": "x2",
                    "mock_responses": ['{"message": "B", "language": "EN"}'],
                },
                "judge": {
                    "provider": "mock",
                    "model": "j",
                    "mock_responses": ['{"message": "Best!", "language": "EN"}'],
                },
            },
            "steps": [
                {
                    "name": "extract",
                    "type": "ensemble",
                    "schema": "tests.fixtures.schemas:Greeting",
                    "members": [{"model": "m1"}, {"model": "m2"}],
                    "judge": {"model": "judge", "prompt": "judge.j2"},
                },
            ],
        }
        p = tmp_path / "explicit_judge_prompt.yaml"
        p.write_text(yaml.dump(spec))
        rctx = PipelineRunner(p).run({})
        assert not rctx.failed
        assert rctx.steps["extract"].value.message == "Best!"

    def test_judge_missing_model_raises(self, tmp_path):
        """G5: judge block without model field → StepConfigError."""
        (tmp_path / "bad.yaml").write_text(
            "models:\n  m:\n    provider: mock\n    model: x\n"
            "steps:\n  - name: e\n    type: ensemble\n    members:\n      - model: m\n"
            "    judge:\n      condition: all_succeeded\n"
        )
        with pytest.raises((StepConfigError, Exception), match="[Mm]odel|model"):
            PipelineRunner(tmp_path / "bad.yaml")

    def test_schema_override_applies_to_ensemble(self, tmp_path):
        """G6: schema override at ensemble level is applied (not recursed into members)."""
        import yaml

        spec = {
            "models": {
                "m": {
                    "provider": "mock",
                    "model": "x",
                    "mock_responses": ['{"message": "Hi!", "language": "EN"}'],
                },
            },
            "steps": [
                {
                    "name": "extract",
                    "type": "ensemble",
                    "schema": "tests.fixtures.schemas:Greeting",
                    "members": [{"model": "m"}],
                },
            ],
        }
        p = tmp_path / "schema_override.yaml"
        p.write_text(yaml.dump(spec))
        from tests.fixtures.schemas import Greeting

        rctx = PipelineRunner(p).run({})
        assert not rctx.failed
        assert isinstance(rctx.steps["extract"].value, Greeting)


# ── Graph visualisation ────────────────────────────────────────────────────────


class TestEnsembleGraph:
    def test_mermaid_contains_ensemble_subgraph(self):
        from pyconveyor.graph import generate_mermaid

        diagram = generate_mermaid(PIPELINES / "ensemble.yaml")
        assert "ensemble: extract" in diagram
        assert "extract.primary" in diagram
        assert "extract.reviewer" in diagram
        assert "extract._judge" in diagram
