"""Tests for vocabulary matching and VocabField pipeline integration."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pyconveyor.vocab import (
    VocabField,
    VocabSuggestion,
    Vocabulary,
    apply_vocab,
    build_vocab_hints,
)

PIPELINES = Path(__file__).parent / "fixtures" / "pipelines"


class TestVocabularyMatch:
    def make(self, known, fuzzy_match=True, case_sensitive=False):
        return Vocabulary(known=set(known), fuzzy_match=fuzzy_match, case_sensitive=case_sensitive)

    def test_exact_match(self):
        v = self.make(["apple", "banana"])
        canonical, match_type = v.match("apple")
        assert canonical == "apple"
        assert match_type == "exact"

    def test_exact_case_insensitive(self):
        v = self.make(["Apple"])
        canonical, match_type = v.match("apple")
        assert canonical == "Apple"
        assert match_type == "exact"

    def test_exact_case_sensitive_no_match(self):
        v = self.make(["Apple"], case_sensitive=True, fuzzy_match=False)
        canonical, match_type = v.match("apple")
        assert match_type == "novel"

    def test_fuzzy_match_substring(self):
        v = self.make(["banana_fruit"])
        canonical, match_type = v.match("banana")
        assert canonical == "banana_fruit"
        assert match_type == "fuzzy"

    def test_novel_no_match(self):
        v = self.make(["apple", "banana"])
        canonical, match_type = v.match("mango")
        assert canonical == "mango"
        assert match_type == "novel"

    def test_novel_fuzzy_disabled(self):
        v = self.make(["banana_fruit"], fuzzy_match=False)
        canonical, match_type = v.match("banana")
        assert match_type == "novel"

    def test_empty_known(self):
        v = self.make([])
        canonical, match_type = v.match("anything")
        assert match_type == "novel"

    def test_from_dict(self):
        v = Vocabulary.from_dict({"known": ["cat", "dog"], "fuzzy_match": True})
        canonical, match_type = v.match("cat")
        assert match_type == "exact"


class TestVocabularyV2:
    def test_description_stored(self):
        v = Vocabulary(known={"PET"}, label="plastic", description="ISO codes")
        assert v.description == "ISO codes"

    def test_invalid_growth_policy_raises(self):
        with pytest.raises(ValueError, match="growth_policy"):
            Vocabulary(known={"A"}, growth_policy="invalid_policy")

    def test_callable_growth_policy_accepted(self):
        v = Vocabulary(known={"A"}, growth_policy=lambda s: True)
        assert callable(v.growth_policy)

    def test_add_term_updates_known_and_lookup(self):
        v = Vocabulary(known={"PET"}, case_sensitive=False)
        v.add_term("HDPE")
        assert "HDPE" in v.known
        canonical, match_type = v.match("hdpe")
        assert canonical == "HDPE"
        assert match_type == "exact"

    def test_add_pending_increments_seen(self):
        v = Vocabulary(known={"PET"})
        s = VocabSuggestion(field_name="p", raw_value="HDPE", matched_to=None, match_type="novel")
        v.add_pending(s)
        v.add_pending(s)
        assert len(v.pending) == 1
        assert v.pending[0]["seen"] == 2

    def test_add_pending_stores_ideal(self):
        v = Vocabulary(known={"PET"})
        s = VocabSuggestion(
            field_name="p", raw_value="PE", matched_to=None,
            match_type="novel", ideal_value="Polyethylene"
        )
        v.add_pending(s)
        assert v.pending[0]["ideal_value"] == "Polyethylene"

    def test_build_prompt_suffix_basic(self):
        v = Vocabulary(known={"PET", "PE"}, label="plastic_type")
        suffix = v.build_prompt_suffix()
        assert "plastic_type" in suffix
        assert "PET" in suffix

    def test_build_prompt_suffix_with_description(self):
        v = Vocabulary(known={"PET"}, label="plastic", description="ISO codes")
        suffix = v.build_prompt_suffix()
        assert "ISO codes" in suffix

    def test_build_prompt_suffix_with_denied(self):
        v = Vocabulary(known={"PET"}, label="plastic", denied={"HDPE"})
        suffix = v.build_prompt_suffix()
        assert "HDPE" in suffix
        assert "excluded" in suffix.lower()

    def test_build_prompt_suffix_capture_ideal(self):
        v = Vocabulary(known={"PET"}, label="plastic", capture_ideal=True)
        suffix = v.build_prompt_suffix()
        assert "plastic_ideal" in suffix

    def test_save_and_load_roundtrip(self, tmp_path):
        v = Vocabulary(
            known={"PET", "PE"},
            label="plastic",
            description="ISO codes",
            growth_policy="auto",
            denied={"HDPE"},
            pending=[{"raw_value": "PP", "seen": 2}],
        )
        path = tmp_path / "plastic.yaml"
        v.save(path)
        v2 = Vocabulary.from_file(path)
        assert v2.known == {"PET", "PE"}
        assert v2.label == "plastic"
        assert v2.description == "ISO codes"
        assert v2.growth_policy == "auto"
        assert "HDPE" in v2.denied
        assert v2.pending[0]["raw_value"] == "PP"

    def test_from_file_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Vocabulary.from_file(tmp_path / "nonexistent.yaml")


class TestBuildVocabHints:
    def test_empty_returns_empty_string(self):
        assert build_vocab_hints({}) == ""

    def test_includes_vocab_label(self):
        v = Vocabulary(known={"PET", "PE"}, label="plastic_type")
        hints = build_vocab_hints({"plastic_type": v})
        assert "plastic_type" in hints

    def test_inject_prompt_false_excluded(self):
        v = Vocabulary(known={"PET"}, label="plastic", inject_prompt=False)
        hints = build_vocab_hints({"plastic": v})
        assert hints == ""


class TestApplyVocab:
    def test_exact_returns_canonical_no_suggestion(self):
        v = Vocabulary(known={"PET", "PE"})
        stored, novel, matched, suggestion = apply_vocab("PET", v, "plastic")
        assert stored == "PET"
        assert novel is None
        assert matched is True
        assert suggestion is None

    def test_case_normalised_exact(self):
        v = Vocabulary(known={"PET", "PE"})
        stored, novel, matched, suggestion = apply_vocab("pet", v, "plastic")
        assert stored == "PET"
        assert matched is True
        assert suggestion is None

    def test_fuzzy_returns_suggestion(self):
        v = Vocabulary(known={"banana_fruit"})
        stored, novel, matched, suggestion = apply_vocab("banana", v, "fruit")
        assert stored == "banana_fruit"
        assert suggestion is not None
        assert suggestion.match_type == "fuzzy"
        assert suggestion.field_name == "fruit"

    def test_novel_returns_suggestion(self):
        v = Vocabulary(known={"apple"})
        stored, novel, matched, suggestion = apply_vocab("mango", v, "fruit")
        assert stored == "mango"
        assert novel == "mango"
        assert matched is False
        assert suggestion is not None
        assert suggestion.match_type == "novel"
        assert suggestion.matched_to is None

    def test_ideal_value_stored_in_suggestion(self):
        v = Vocabulary(known={"PET"})
        stored, novel, matched, suggestion = apply_vocab("HDPE", v, "plastic", ideal_value="Polyethylene")
        assert suggestion is not None
        assert suggestion.ideal_value == "Polyethylene"

    def test_vocab_label_stored_in_suggestion(self):
        v = Vocabulary(known={"PET"}, label="plastic_type")
        _, _, _, suggestion = apply_vocab("HDPE", v, "plastic")
        assert suggestion.vocab_label == "plastic_type"


class TestVocabFieldV2:
    def test_string_ref_stored(self):
        from pydantic.fields import FieldInfo
        fi = VocabField(vocab="plastic_type")
        assert isinstance(fi, FieldInfo)
        assert fi.json_schema_extra["_pyconveyor_vocab_ref"] == "plastic_type"

    def test_vocabulary_object_stored(self):
        v = Vocabulary(known={"PET"})
        fi = VocabField(vocab=v)
        assert fi.json_schema_extra["_pyconveyor_vocab"] is v

    def test_capture_ideal_stored(self):
        v = Vocabulary(known={"PET"})
        fi = VocabField(vocab=v, capture_ideal=True)
        assert fi.json_schema_extra["_pyconveyor_capture_ideal"] is True


class TestVocabFieldPipelineIntegration:
    """Test that VocabField metadata is picked up by the LLM step post-processor."""

    def test_exact_match_normalised_in_result(self):
        from pyconveyor import PipelineRunner
        runner = PipelineRunner(PIPELINES / "vocab_pipeline.yaml")
        rctx = runner.run({})
        assert not rctx.failed
        result = rctx.steps["extract"].value
        assert result.plastic == "PET"

    def test_no_vocab_suggestions_on_exact_match(self):
        from pyconveyor import PipelineRunner
        runner = PipelineRunner(PIPELINES / "vocab_pipeline.yaml")
        rctx = runner.run({})
        assert rctx._vocab_suggestions == []

    def test_novel_value_stored_as_suggestion(self, tmp_path):
        from pyconveyor import PipelineRunner

        pipeline = tmp_path / "vocab_novel.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"HDPE\", \"quantity\": 3}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract plastic type.'\n"
            "    schema: tests.fixtures.schemas:PlasticRecord\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        rctx = runner.run({})
        assert not rctx.failed
        assert len(rctx._vocab_suggestions) == 1
        s = rctx._vocab_suggestions[0]
        assert s.field_name == "plastic"
        assert s.raw_value == "HDPE"

    def test_run_summary_exposes_vocab_suggestions(self):
        from pyconveyor import PipelineRunner
        runner = PipelineRunner(PIPELINES / "vocab_pipeline.yaml")
        rctx = runner.run({})
        summary = rctx.summary()
        assert isinstance(summary.vocab_suggestions, list)

    def test_capture_ideal_extracted_from_response(self, tmp_path):
        """When capture_ideal=True, {field}_ideal is popped from response and stored in suggestion."""
        from pydantic import BaseModel

        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import VocabField, Vocabulary

        vocab = Vocabulary(known={"PET", "PE"}, label="plastic_type", capture_ideal=True)

        class CaptureRecord(BaseModel):
            plastic: str = VocabField(vocab=vocab, capture_ideal=True)
            quantity: int

        # Save schema to tmp_path so it's importable
        import sys
        sys.modules["_test_capture_schema"] = type(sys)("_test_capture_schema")
        sys.modules["_test_capture_schema"].CaptureRecord = CaptureRecord  # type: ignore[attr-defined]

        pipeline = tmp_path / "capture.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"HDPE\", \"plastic_ideal\": \"High Density Polyethylene\", \"quantity\": 3}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema: _test_capture_schema:CaptureRecord\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        rctx = runner.run({})
        assert not rctx.failed
        assert len(rctx._vocab_suggestions) == 1
        s = rctx._vocab_suggestions[0]
        assert s.ideal_value == "High Density Polyethylene"


class TestVocabGrowthPolicy:
    def test_auto_policy_adds_novel_term(self, tmp_path):
        from pydantic import BaseModel

        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import VocabField, Vocabulary

        vocab = Vocabulary(
            known={"PET"}, label="plastic_type", growth_policy="auto",
        )

        class AutoRecord(BaseModel):
            plastic: str = VocabField(vocab=vocab)
            quantity: int

        import sys
        sys.modules["_test_auto_schema"] = type(sys)("_test_auto_schema")
        sys.modules["_test_auto_schema"].AutoRecord = AutoRecord  # type: ignore[attr-defined]

        pipeline = tmp_path / "auto.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"HDPE\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema: _test_auto_schema:AutoRecord\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        rctx = runner.run({})
        assert not rctx.failed
        # auto policy: HDPE should now be in known
        assert "HDPE" in vocab.known

    def test_human_policy_queues_pending(self, tmp_path):
        from pydantic import BaseModel

        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import VocabField, Vocabulary

        vocab = Vocabulary(
            known={"PET"}, label="plastic_type", growth_policy="human",
        )

        class HumanRecord(BaseModel):
            plastic: str = VocabField(vocab=vocab)
            quantity: int

        import sys
        sys.modules["_test_human_schema"] = type(sys)("_test_human_schema")
        sys.modules["_test_human_schema"].HumanRecord = HumanRecord  # type: ignore[attr-defined]

        pipeline = tmp_path / "human.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"HDPE\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema: _test_human_schema:HumanRecord\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        rctx = runner.run({})
        assert not rctx.failed
        # human policy: HDPE should NOT be in known
        assert "HDPE" not in vocab.known
        # But queued in pending
        assert any(e["raw_value"] == "HDPE" for e in vocab.pending)

    def test_callable_policy_called_with_suggestion(self, tmp_path):
        from pydantic import BaseModel

        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import VocabField, Vocabulary

        received: list[VocabSuggestion] = []

        def my_policy(suggestion: VocabSuggestion) -> bool:
            received.append(suggestion)
            return False  # deny

        vocab = Vocabulary(
            known={"PET"}, label="plastic_type", growth_policy=my_policy,
        )

        class CallableRecord(BaseModel):
            plastic: str = VocabField(vocab=vocab)
            quantity: int

        import sys
        sys.modules["_test_callable_schema"] = type(sys)("_test_callable_schema")
        sys.modules["_test_callable_schema"].CallableRecord = CallableRecord  # type: ignore[attr-defined]

        pipeline = tmp_path / "callable.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"HDPE\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema: _test_callable_schema:CallableRecord\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        runner.run({})
        assert len(received) == 1
        assert received[0].raw_value == "HDPE"

    def test_vocab_persist_saves_file(self, tmp_path):
        from pydantic import BaseModel

        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import VocabField, Vocabulary

        persist_path = tmp_path / "vocab" / "plastic.yaml"
        vocab = Vocabulary(
            known={"PET"}, label="plastic_type",
            growth_policy="auto",
            persist=str(persist_path),
        )

        class PersistRecord(BaseModel):
            plastic: str = VocabField(vocab=vocab)
            quantity: int

        import sys
        sys.modules["_test_persist_schema"] = type(sys)("_test_persist_schema")
        sys.modules["_test_persist_schema"].PersistRecord = PersistRecord  # type: ignore[attr-defined]

        pipeline = tmp_path / "persist.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"HDPE\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema: _test_persist_schema:PersistRecord\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        runner.run({})
        assert persist_path.exists()
        import yaml
        data = yaml.safe_load(persist_path.read_text())
        assert "HDPE" in data["known"]


class TestVocabFileLoading:
    def test_vocabulary_loaded_from_file(self, tmp_path):
        """Runner loads vocab from vocabularies/ directory relative to pipeline."""
        from pydantic import BaseModel

        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import VocabField, Vocabulary

        # Place vocab file in vocabularies/ relative to pipeline dir
        vocab_dir = tmp_path / "vocabularies"
        vocab_dir.mkdir()
        vocab_file = vocab_dir / "plastic_type.yaml"
        Vocabulary(known={"PET", "PE"}, label="plastic_type").save(vocab_file)

        # Schema using string ref — resolved via vocabularies/ directory auto-load
        class RefRecord(BaseModel):
            plastic: str = VocabField(vocab="plastic_type")
            quantity: int

        import sys
        sys.modules["_test_ref_schema"] = type(sys)("_test_ref_schema")
        sys.modules["_test_ref_schema"].RefRecord = RefRecord  # type: ignore[attr-defined]

        pipeline = tmp_path / "ref_pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"pet\", \"quantity\": 2}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema: _test_ref_schema:RefRecord\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        rctx = runner.run({})
        assert not rctx.failed
        # "pet" should normalise to "PET" via the loaded vocab file
        assert rctx.steps["extract"].value.plastic == "PET"


class TestVocabPromptInjection:
    def test_vocab_suffix_appended_to_prompt(self, tmp_path):
        """Vocab constraints are appended to the LLM prompt automatically."""
        from pydantic import BaseModel

        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import VocabField, Vocabulary

        vocab = Vocabulary(known={"PET", "PE"}, label="plastic_type")
        captured_messages: list = []

        class InjRecord(BaseModel):
            plastic: str = VocabField(vocab=vocab)
            quantity: int

        import sys
        sys.modules["_test_inj_schema"] = type(sys)("_test_inj_schema")
        sys.modules["_test_inj_schema"].InjRecord = InjRecord  # type: ignore[attr-defined]

        pipeline = tmp_path / "inj.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"PET\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract plastic type.'\n"
            "    schema: _test_inj_schema:InjRecord\n"
            "    max_attempts: 1\n"
        )


        def fake_call_llm(client, messages, model, **kwargs):
            captured_messages.extend(messages)
            return '{"plastic": "PET", "quantity": 1}', None

        with patch("pyconveyor.steps.llm_step.call_llm", side_effect=fake_call_llm):
            runner = PipelineRunner(pipeline)
            runner.run({})

        assert captured_messages, "No messages captured"
        prompt_text = " ".join(m.get("content", "") for m in captured_messages)
        assert "plastic_type" in prompt_text


class TestOnLlmCallParallelFix:
    def test_on_llm_call_fires_for_parallel_children(self, tmp_path):
        """Regression: on_llm_call must fire for LLM calls inside parallel steps."""
        from pyconveyor import PipelineRunner

        pipeline = tmp_path / "par_hooks.yaml"
        pipeline.write_text(
            "models:\n"
            "  m:\n"
            "    provider: mock\n"
            "    model: m\n"
            "    mock_responses:\n"
            "      - '{\"message\": \"hi\", \"language\": \"en\"}'\n"
            "      - '{\"message\": \"hello\", \"language\": \"en\"}'\n"
            "steps:\n"
            "  - name: par\n"
            "    type: parallel\n"
            "    steps:\n"
            "      - name: child_a\n"
            "        type: llm\n"
            "        model: m\n"
            "        prompt_string: 'Hello'\n"
            "        schema: tests.fixtures.schemas:Greeting\n"
            "        max_attempts: 1\n"
            "      - name: child_b\n"
            "        type: llm\n"
            "        model: m\n"
            "        prompt_string: 'Hello'\n"
            "        schema: tests.fixtures.schemas:Greeting\n"
            "        max_attempts: 1\n"
        )
        calls: list[tuple] = []
        runner = PipelineRunner(pipeline)
        runner.on_llm_call(lambda step, model, response: calls.append((step, model, response)))
        rctx = runner.run({})
        assert not rctx.failed
        # Both parallel children should have fired on_llm_call
        assert len(calls) == 2
        step_names = {c[0] for c in calls}
        assert "child_a" in step_names
        assert "child_b" in step_names


class TestVocabCliReview:
    def test_review_auto_accept(self, tmp_path):
        """--auto-accept moves all pending into known and clears pending."""
        from pyconveyor.vocab import Vocabulary

        vocab = Vocabulary(
            known={"PET"}, label="plastic_type", growth_policy="human",
        )
        vocab.pending = [{"raw_value": "HDPE", "seen": 2, "match_type": "novel"}]
        vocab_path = tmp_path / "vocabularies" / "plastic_type.yaml"
        vocab.save(vocab_path)

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n  default:\n    provider: mock\n    model: m\n    mock_responses: ['\"x\"']\n"
            "steps:\n  - name: s\n    type: llm\n    model: default\n    prompt_string: 'x'\n"
        )

        from unittest.mock import patch

        from pyconveyor.cli import main

        with patch("sys.argv", ["pyconveyor", "vocab", "review", str(pipeline), "--auto-accept"]):
            with patch("sys.stdout"):
                main()

        updated = Vocabulary.from_file(vocab_path)
        assert "HDPE" in updated.known
        assert updated.pending == []

    def test_review_no_pending(self, tmp_path, capsys):
        """No-op when no pending suggestions exist."""
        from pyconveyor.vocab import Vocabulary

        vocab = Vocabulary(known={"PET"}, label="plastic_type")
        vocab_path = tmp_path / "vocabularies" / "plastic_type.yaml"
        vocab.save(vocab_path)

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n  default:\n    provider: mock\n    model: m\n    mock_responses: ['\"x\"']\n"
            "steps:\n  - name: s\n    type: llm\n    model: default\n    prompt_string: 'x'\n"
        )

        from unittest.mock import patch

        from pyconveyor.cli import main

        with patch("sys.argv", ["pyconveyor", "vocab", "review", str(pipeline)]):
            main()

        captured = capsys.readouterr()
        assert "No pending" in captured.out


class TestVocabAdditionalCoverage:
    def test_inject_vocab_prompt_false_suppresses_suffix(self, tmp_path):
        """When inject_vocab_prompt: false, the vocab suffix is NOT appended."""
        from pydantic import BaseModel

        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import VocabField, Vocabulary

        vocab = Vocabulary(known={"PET", "PE"}, label="plastic_type")
        captured_messages: list = []

        class NoInjectRecord(BaseModel):
            plastic: str = VocabField(vocab=vocab)
            quantity: int

        import sys
        sys.modules["_test_noinj_schema"] = type(sys)("_test_noinj_schema")
        sys.modules["_test_noinj_schema"].NoInjectRecord = NoInjectRecord  # type: ignore[attr-defined]

        pipeline = tmp_path / "noinj.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"PET\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    inject_vocab_prompt: false\n"
            "    prompt_string: 'Extract plastic type.'\n"
            "    schema: _test_noinj_schema:NoInjectRecord\n"
            "    max_attempts: 1\n"
        )

        def fake_call_llm(client, messages, model, **kwargs):
            captured_messages.extend(messages)
            return '{"plastic": "PET", "quantity": 1}', None

        with patch("pyconveyor.steps.llm_step.call_llm", side_effect=fake_call_llm):
            runner = PipelineRunner(pipeline)
            runner.run({})

        prompt_text = " ".join(m.get("content", "") for m in captured_messages)
        assert "Vocabulary constraint" not in prompt_text

    def test_persist_true_uses_default_path(self, tmp_path):
        """persist=True saves to vocabularies/{label}.yaml relative to pipeline dir."""
        from pydantic import BaseModel

        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import VocabField, Vocabulary

        vocab = Vocabulary(
            known={"PET"}, label="plastic_type",
            growth_policy="auto",
            persist=True,
        )

        class PersistTrueRecord(BaseModel):
            plastic: str = VocabField(vocab=vocab)
            quantity: int

        import sys
        sys.modules["_test_persist_true_schema"] = type(sys)("_test_persist_true_schema")
        sys.modules["_test_persist_true_schema"].PersistTrueRecord = PersistTrueRecord  # type: ignore[attr-defined]

        pipeline = tmp_path / "persist_true.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"HDPE\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema: _test_persist_true_schema:PersistTrueRecord\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        runner.run({})
        default_path = tmp_path / "vocabularies" / "plastic_type.yaml"
        assert default_path.exists()

    def test_llm_growth_policy_accepts_term(self, tmp_path):
        """growth_policy='llm' calls _llm_growth_decision; accepted terms added to known."""
        from pydantic import BaseModel

        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import VocabField, Vocabulary

        vocab = Vocabulary(
            known={"PET"}, label="plastic_type",
            growth_policy="llm",
        )

        class LlmPolicyRecord(BaseModel):
            plastic: str = VocabField(vocab=vocab)
            quantity: int

        import sys
        sys.modules["_test_llmpol_schema"] = type(sys)("_test_llmpol_schema")
        sys.modules["_test_llmpol_schema"].LlmPolicyRecord = LlmPolicyRecord  # type: ignore[attr-defined]

        pipeline = tmp_path / "llmpol.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"HDPE\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema: _test_llmpol_schema:LlmPolicyRecord\n"
            "    max_attempts: 1\n"
        )

        runner = PipelineRunner(pipeline)
        with patch.object(runner, "_llm_growth_decision", return_value=True):
            runner.run({})

        assert "HDPE" in vocab.known

    def test_llm_growth_policy_rejects_term(self, tmp_path):
        """growth_policy='llm' calls _llm_growth_decision; rejected terms not added."""
        from pydantic import BaseModel

        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import VocabField, Vocabulary

        vocab = Vocabulary(
            known={"PET"}, label="plastic_type",
            growth_policy="llm",
        )

        class LlmPolRejectRecord(BaseModel):
            plastic: str = VocabField(vocab=vocab)
            quantity: int

        import sys
        sys.modules["_test_llmpolrej_schema"] = type(sys)("_test_llmpolrej_schema")
        sys.modules["_test_llmpolrej_schema"].LlmPolRejectRecord = LlmPolRejectRecord  # type: ignore[attr-defined]

        pipeline = tmp_path / "llmpolrej.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"HDPE\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema: _test_llmpolrej_schema:LlmPolRejectRecord\n"
            "    max_attempts: 1\n"
        )

        runner = PipelineRunner(pipeline)
        with patch.object(runner, "_llm_growth_decision", return_value=False):
            runner.run({})

        assert "HDPE" not in vocab.known


# ── Vocab in YAML schemas — integration tests ──────────────────────────────────


class TestVocabInSchemasIntegration:
    """End-to-end tests for vocabs defined inline in YAML schema fields."""

    def test_inline_vocab_normalizes_llm_output(self, tmp_path):
        from pyconveyor import PipelineRunner

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"pet\", \"quantity\": 3}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema:\n"
            "      plastic:\n"
            "        type: str\n"
            "        vocab:\n"
            "          known: [PET, PE, PLA]\n"
            "      quantity: int\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        rctx = runner.run({})
        assert not rctx.failed
        result = rctx.steps["extract"].value
        assert result.plastic == "PET"

    def test_inline_vocab_creates_suggestion_for_novel(self, tmp_path):
        from pyconveyor import PipelineRunner

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"PVC\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema:\n"
            "      plastic:\n"
            "        type: str\n"
            "        vocab:\n"
            "          known: [PET, PE]\n"
            "      quantity: int\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        rctx = runner.run({})
        assert not rctx.failed
        assert len(rctx._vocab_suggestions) == 1
        s = rctx._vocab_suggestions[0]
        assert s.raw_value == "PVC"
        assert s.match_type == "novel"

    def test_inline_vocab_auto_growth_adds_term(self, tmp_path):
        from pyconveyor import PipelineRunner

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"HDPE\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema:\n"
            "      plastic:\n"
            "        type: str\n"
            "        vocab:\n"
            "          known: [PET, PE]\n"
            "          growth_policy: auto\n"
            "      quantity: int\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        rctx = runner.run({})
        assert not rctx.failed
        # Growth policy "auto" should add HDPE to known
        extra = rctx.steps["extract"].value.model_fields["plastic"].json_schema_extra
        vocab = extra["_pyconveyor_vocab"]
        assert "HDPE" in vocab.known

    def test_file_vocab_loaded_from_vocabularies_dir(self, tmp_path):
        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import Vocabulary

        # Place vocab file in vocabularies/
        vocab_dir = tmp_path / "vocabularies"
        vocab_dir.mkdir()
        vocab_file = vocab_dir / "plastic.yaml"
        Vocabulary(
            known={"PET", "PE"}, label="plastic",
            description="Resin codes",
        ).save(vocab_file)

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"pet\", \"quantity\": 2}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema:\n"
            "      plastic:\n"
            "        type: str\n"
            "        vocab: plastic\n"
            "      quantity: int\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        rctx = runner.run({})
        assert not rctx.failed
        result = rctx.steps["extract"].value
        assert result.plastic == "PET"

    def test_file_vocab_ref_resolves_description(self, tmp_path):
        """Vocab file description should be stored on the resolved vocab."""
        from pyconveyor import PipelineRunner
        from pyconveyor.vocab import Vocabulary

        vocab_dir = tmp_path / "vocabularies"
        vocab_dir.mkdir()
        vocab_file = vocab_dir / "color.yaml"
        Vocabulary(
            known={"red", "green"}, label="color",
            description="Valid color names",
        ).save(vocab_file)

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"color\": \"red\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema:\n"
            "      color:\n"
            "        type: str\n"
            "        vocab: color\n"
            "      quantity: int\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        rctx = runner.run({})
        assert not rctx.failed
        # Check that the vocab description is on the field's json_schema_extra
        extra = rctx.steps["extract"].value.model_fields["color"].json_schema_extra
        assert extra["_pyconveyor_vocab"].description == "Valid color names"

    def test_vocab_prompt_injection_filtered_to_schema(self, tmp_path):
        """Only vocabs referenced by the schema appear in the prompt."""
        from unittest.mock import patch

        from pyconveyor import PipelineRunner

        # Create both a plastic vocab file AND a color vocab file
        vocab_dir = tmp_path / "vocabularies"
        vocab_dir.mkdir()
        (vocab_dir / "plastic.yaml").write_text(
            "label: plastic\nknown:\n  - PET\n  - PE\n"
        )
        (vocab_dir / "color.yaml").write_text(
            "label: color\nknown:\n  - red\n  - green\n"
        )

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"PET\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema:\n"
            "      plastic:\n"
            "        type: str\n"
            "        vocab: plastic\n"
            "      quantity: int\n"
            "    max_attempts: 1\n"
        )

        captured_messages: list = []

        def fake_call_llm(client, messages, model, **kwargs):
            captured_messages.extend(messages)
            return '{"plastic": "PET", "quantity": 1}', None

        with patch("pyconveyor.steps.llm_step.call_llm", side_effect=fake_call_llm):
            runner = PipelineRunner(pipeline)
            runner.run({})

        prompt_text = " ".join(m.get("content", "") for m in captured_messages)
        # Should contain plastic vocab (referenced by schema)
        assert "plastic" in prompt_text
        # Should NOT contain color vocab (not referenced by schema)
        assert "color" not in prompt_text

    def test_no_vocab_injected_when_schema_has_no_vocab_fields(self, tmp_path):
        """When schema exists but has no vocab fields, no vocab hints are injected."""
        from unittest.mock import patch

        from pyconveyor import PipelineRunner

        vocab_dir = tmp_path / "vocabularies"
        vocab_dir.mkdir()
        (vocab_dir / "unused.yaml").write_text(
            "label: unused\nknown:\n  - A\n  - B\n"
        )

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"name\": \"test\", \"quantity\": 1}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema:\n"
            "      name: str\n"
            "      quantity: int\n"
            "    max_attempts: 1\n"
        )

        captured_messages: list = []

        def fake_call_llm(client, messages, model, **kwargs):
            captured_messages.extend(messages)
            return '{"name": "test", "quantity": 1}', None

        with patch("pyconveyor.steps.llm_step.call_llm", side_effect=fake_call_llm):
            runner = PipelineRunner(pipeline)
            runner.run({})

        prompt_text = " ".join(m.get("content", "") for m in captured_messages)
        assert "Vocabulary constraint" not in prompt_text
        assert "unused" not in prompt_text

    def test_inline_vocab_in_schema_file_referenced_by_ref(self, tmp_path):
        """A vocab in a $ref'd schema file works end-to-end."""
        from pyconveyor import PipelineRunner

        # Write the schema file referenced by $ref
        schema_file = tmp_path / "schemas" / "extract.yaml"
        schema_file.parent.mkdir()
        schema_file.write_text(
            "plastic:\n"
            "  type: str\n"
            "  vocab:\n"
            "    known: [PET, PE, PLA]\n"
            "quantity: int\n"
        )

        pipeline = tmp_path / "pipeline.yaml"
        pipeline.write_text(
            "models:\n"
            "  default:\n"
            "    provider: mock\n"
            "    model: mock-model\n"
            "    mock_responses:\n"
            "      - '{\"plastic\": \"pet\", \"quantity\": 3}'\n"
            "steps:\n"
            "  - name: extract\n"
            "    type: llm\n"
            "    model: default\n"
            "    prompt_string: 'Extract.'\n"
            "    schema:\n"
            "      $ref: schemas/extract.yaml\n"
            "    max_attempts: 1\n"
        )
        runner = PipelineRunner(pipeline)
        rctx = runner.run({})
        assert not rctx.failed
        result = rctx.steps["extract"].value
        assert result.plastic == "PET"
