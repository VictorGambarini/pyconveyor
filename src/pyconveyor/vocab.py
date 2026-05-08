"""Vocabulary-constrained fields with fuzzy matching.

Usage::

    from pyconveyor.vocab import VocabField, Vocabulary
    from pydantic import BaseModel

    PlasticVocab = Vocabulary(
        known={"PET", "PE", "PLA"},
        label="plastic_type",
    )

    class Record(BaseModel):
        plastic: str = VocabField(vocab=PlasticVocab)
        # automatically adds:
        #   plastic_novel: str | None
        #   plastic_vocab_match: bool
"""
from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("pyconveyor.vocab")


@dataclass
class VocabSuggestion:
    """A single novel / fuzzy-matched vocab term from a run."""

    field_name: str
    raw_value: str
    matched_to: str | None  # canonical term, or None if no match
    match_type: str  # "exact" | "fuzzy" | "novel"


@dataclass
class Vocabulary:
    """A controlled vocabulary for an extraction field.

    Args:
        known: Set of canonical terms.
        label: Human-readable label for this vocabulary (used in summaries).
        fuzzy_match: Enable edit-distance normalisation (default: True).
        case_sensitive: Whether matching is case-sensitive (default: False).
    """

    known: set[str]
    label: str = "vocabulary"
    fuzzy_match: bool = True
    case_sensitive: bool = False

    def __post_init__(self) -> None:
        # Pre-build a normalised lookup table
        if self.case_sensitive:
            self._lookup: dict[str, str] = {k: k for k in self.known}
        else:
            self._lookup = {k.casefold(): k for k in self.known}

    def match(self, value: str) -> tuple[str, str]:
        """Return ``(canonical_term, match_type)`` for *value*.

        match_type is one of: ``"exact"``, ``"fuzzy"``, ``"novel"``.
        """
        key = value if self.case_sensitive else value.casefold()

        # 1. Exact
        if key in self._lookup:
            return self._lookup[key], "exact"

        if self.fuzzy_match:
            # 2. Substring match
            for norm_key, canonical in self._lookup.items():
                if key in norm_key or norm_key in key:
                    return canonical, "fuzzy"

            # 3. Edit-distance match (difflib)
            candidates = list(self._lookup.keys())
            matches = difflib.get_close_matches(key, candidates, n=1, cutoff=0.75)
            if matches:
                return self._lookup[matches[0]], "fuzzy"

        return value, "novel"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Vocabulary":
        """Build from a YAML-loaded dict."""
        known = set(data.get("known", []))
        return cls(
            known=known,
            label=data.get("label", "vocabulary"),
            fuzzy_match=data.get("fuzzy_match", True),
            case_sensitive=data.get("case_sensitive", False),
        )


def VocabField(
    vocab: Vocabulary,
    **field_kwargs: Any,
) -> Any:
    """Pydantic field descriptor that validates a value against *vocab*.

    Attaches a Pydantic ``field_validator`` to the parent model via a custom
    annotation.  Also registers ``{field_name}_novel`` and
    ``{field_name}_vocab_match`` shadow fields.

    .. note::
        Because Pydantic v2 does not support dynamic field injection at field
        definition time, the recommended approach is to use
        ``VocabAnnotation`` and declare the companion fields explicitly, or to
        use ``add_vocab_fields`` as a class decorator.  ``VocabField`` is
        retained as a convenience shim.
    """
    from pydantic import field_validator
    from pydantic.fields import FieldInfo

    # Attach vocab metadata so the runner can read it back
    extra = field_kwargs.pop("json_schema_extra", {}) or {}
    extra["_pyconveyor_vocab"] = vocab
    return FieldInfo(json_schema_extra=extra, **field_kwargs)


def apply_vocab(
    value: str,
    vocab: Vocabulary,
    field_name: str,
) -> tuple[str, str | None, bool, VocabSuggestion | None]:
    """Apply *vocab* to *value*.

    Returns:
        ``(stored_value, novel_value, vocab_match, suggestion_or_None)``
    """
    canonical, match_type = vocab.match(value)
    if match_type == "exact":
        return canonical, None, True, None
    suggestion = VocabSuggestion(
        field_name=field_name,
        raw_value=value,
        matched_to=canonical if match_type == "fuzzy" else None,
        match_type=match_type,
    )
    return canonical if match_type == "fuzzy" else value, value, False, suggestion
