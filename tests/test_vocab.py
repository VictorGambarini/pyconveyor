"""Tests for vocabulary matching and VocabField pipeline integration."""
from __future__ import annotations

from pathlib import Path

from pyconveyor.vocab import Vocabulary, apply_vocab

PIPELINES = Path(__file__).parent / "fixtures" / "pipelines"


class TestVocabularyMatch:
    def make(self, known, fuzzy_match=True, case_sensitive=False):
        return Vocabulary(known=known, fuzzy_match=fuzzy_match, case_sensitive=case_sensitive)

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
