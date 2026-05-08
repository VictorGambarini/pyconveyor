"""Tests for vocabulary matching."""
from __future__ import annotations

import pytest

from pyconveyor.vocab import Vocabulary


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
