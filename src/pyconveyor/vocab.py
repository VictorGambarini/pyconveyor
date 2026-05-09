"""Vocabulary-constrained fields with fuzzy matching, growth policies, and persistence.

Usage::

    from pyconveyor.vocab import VocabField, Vocabulary
    from pydantic import BaseModel

    PlasticVocab = Vocabulary(
        known={"PET", "PE", "PLA"},
        label="plastic_type",
        description="Standard resin codes from ISO 1043.",
        growth_policy="human",
        persist="vocabularies/plastic_type.yaml",
    )

    class Record(BaseModel):
        plastic: str = VocabField(vocab=PlasticVocab, capture_ideal=True)
"""
from __future__ import annotations

import difflib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("pyconveyor.vocab")

GROWTH_POLICIES = ("auto", "human", "llm")


@dataclass
class VocabSuggestion:
    """A single novel / fuzzy-matched vocab term from a run."""

    field_name: str
    raw_value: str
    matched_to: str | None  # canonical term, or None if no match
    match_type: str  # "exact" | "fuzzy" | "novel"
    ideal_value: str | None = None  # LLM's unconstrained preferred value
    vocab_label: str | None = None  # which vocabulary this came from
    _vocab: Any = field(default=None, repr=False, compare=False)  # Vocabulary object reference


@dataclass
class Vocabulary:
    """A controlled vocabulary for an extraction field.

    Args:
        known: Set of canonical terms.
        label: Human-readable label for this vocabulary (used in summaries).
        description: Human-written rationale — what criteria justify adding a term.
            Shown to the LLM in the prompt suffix when provided.
        fuzzy_match: Enable edit-distance normalisation (default: True).
        case_sensitive: Whether matching is case-sensitive (default: False).
        growth_policy: How novel terms are handled after each run.
            ``"auto"`` adds them immediately.
            ``"human"`` queues them in *persist* file for CLI review.
            ``"llm"`` fires an LLM call to decide.
            A callable receives a ``VocabSuggestion`` and returns ``bool``.
        growth_policy_model: Name of model (from pipeline ``models:`` block) to use
            for ``growth_policy="llm"``. Falls back to the pipeline's default model.
        capture_ideal: When True, the LLM prompt asks for ``{field}_ideal`` alongside
            the constrained value. The ideal value is stored in the suggestion.
        inject_prompt: When True (default), vocab context is appended to the LLM prompt
            automatically. Set False if using ``{{ vocab_hints }}`` manually.
        persist: Path to a YAML file for persisting ``known``, ``pending``, and
            ``denied`` across runs. Pass True to use ``vocabularies/{label}.yaml``
            relative to the pipeline directory.
        pending: Suggestions awaiting human or LLM review (populated at runtime).
        denied: Terms explicitly rejected; not re-surfaced as suggestions.
    """

    known: set[str]
    label: str = "vocabulary"
    description: str | None = None
    fuzzy_match: bool = True
    case_sensitive: bool = False
    growth_policy: str | Callable[..., bool] = "human"
    growth_policy_model: str | None = None
    capture_ideal: bool = False
    inject_prompt: bool = True
    persist: bool | str | Path | None = None
    pending: list[dict[str, Any]] = field(default_factory=list)
    denied: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.case_sensitive:
            self._lookup: dict[str, str] = {k: k for k in self.known}
        else:
            self._lookup = {k.casefold(): k for k in self.known}
        if isinstance(self.growth_policy, str) and self.growth_policy not in GROWTH_POLICIES:
            raise ValueError(
                f"growth_policy must be one of {GROWTH_POLICIES} or a callable, "
                f"got {self.growth_policy!r}"
            )

    def match(self, value: str) -> tuple[str, str]:
        """Return ``(canonical_term, match_type)`` for *value*.

        match_type is one of: ``"exact"``, ``"fuzzy"``, ``"novel"``.
        """
        key = value if self.case_sensitive else value.casefold()

        if key in self._lookup:
            return self._lookup[key], "exact"

        if self.fuzzy_match:
            for norm_key, canonical in self._lookup.items():
                if key in norm_key or norm_key in key:
                    return canonical, "fuzzy"
            candidates = list(self._lookup.keys())
            matches = difflib.get_close_matches(key, candidates, n=1, cutoff=0.75)
            if matches:
                return self._lookup[matches[0]], "fuzzy"

        return value, "novel"

    def add_term(self, term: str) -> None:
        """Add *term* to ``known`` and update the internal lookup."""
        self.known.add(term)
        key = term if self.case_sensitive else term.casefold()
        self._lookup[key] = term

    def add_pending(self, suggestion: VocabSuggestion) -> None:
        """Queue *suggestion* in ``pending``, incrementing ``seen`` if already present."""
        for entry in self.pending:
            if entry.get("raw_value") == suggestion.raw_value:
                entry["seen"] = entry.get("seen", 1) + 1
                if suggestion.ideal_value and not entry.get("ideal_value"):
                    entry["ideal_value"] = suggestion.ideal_value
                return
        self.pending.append({
            "raw_value": suggestion.raw_value,
            "ideal_value": suggestion.ideal_value,
            "matched_to": suggestion.matched_to,
            "match_type": suggestion.match_type,
            "seen": 1,
        })

    def build_prompt_suffix(self) -> str:
        """Return the vocab constraint block appended to LLM prompts."""
        terms = ", ".join(sorted(self.known))
        lines = [f"Vocabulary constraint for `{self.label}`: choose from [{terms}]."]
        if self.description:
            lines.append(f"Description: {self.description}")
        if self.denied:
            denied_str = ", ".join(sorted(self.denied))
            lines.append(f"Do not suggest: [{denied_str}] — these have been explicitly excluded.")
        if self.capture_ideal:
            lines.append(
                f"Also return `{self.label}_ideal` with your unconstrained best answer "
                f"(what you would say if not limited to the vocabulary above)."
            )
        return "\n".join(lines)

    def save(self, path: str | Path) -> None:
        """Persist this vocabulary to a YAML file."""
        import yaml  # lazy import — yaml is always available via pyyaml

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "label": self.label,
            "fuzzy_match": self.fuzzy_match,
            "case_sensitive": self.case_sensitive,
            "growth_policy": self.growth_policy if isinstance(self.growth_policy, str) else "auto",
            "capture_ideal": self.capture_ideal,
            "inject_prompt": self.inject_prompt,
            "known": sorted(self.known),
            "denied": sorted(self.denied),
            "pending": self.pending,
        }
        if self.description:
            data["description"] = self.description
        if self.growth_policy_model:
            data["growth_policy_model"] = self.growth_policy_model
        with open(p, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    @classmethod
    def from_file(cls, path: str | Path) -> Vocabulary:
        """Load a vocabulary from a YAML file."""
        import yaml

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls._from_data(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Vocabulary:
        """Build from a YAML-loaded dict."""
        return cls._from_data(data)

    @classmethod
    def _from_data(cls, data: dict[str, Any]) -> Vocabulary:
        known = set(data.get("known", []))
        denied = set(data.get("denied", []))
        pending = list(data.get("pending", []))
        return cls(
            known=known,
            label=data.get("label", "vocabulary"),
            description=data.get("description"),
            fuzzy_match=data.get("fuzzy_match", True),
            case_sensitive=data.get("case_sensitive", False),
            growth_policy=data.get("growth_policy", "human"),
            growth_policy_model=data.get("growth_policy_model"),
            capture_ideal=data.get("capture_ideal", False),
            inject_prompt=data.get("inject_prompt", True),
            denied=denied,
            pending=pending,
        )


def VocabField(  # noqa: N802
    vocab: Vocabulary | str,
    capture_ideal: bool = False,
    **field_kwargs: Any,
) -> Any:
    """Pydantic field that validates a value against *vocab*.

    Args:
        vocab: A ``Vocabulary`` instance, or a string label referencing a vocabulary
            declared in ``pipeline.yaml`` under ``vocabularies:``.
        capture_ideal: When True, the LLM is asked to also return ``{field}_ideal``
            with its unconstrained preferred answer. Stored in ``VocabSuggestion``.
    """
    from pydantic.fields import FieldInfo

    extra = field_kwargs.pop("json_schema_extra", {}) or {}
    if isinstance(vocab, str):
        extra["_pyconveyor_vocab_ref"] = vocab
    else:
        extra["_pyconveyor_vocab"] = vocab
    extra["_pyconveyor_capture_ideal"] = capture_ideal
    return FieldInfo(json_schema_extra=extra, **field_kwargs)


def apply_vocab(
    value: str,
    vocab: Vocabulary,
    field_name: str,
    ideal_value: str | None = None,
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
        ideal_value=ideal_value,
        vocab_label=vocab.label,
        _vocab=vocab,
    )
    return canonical if match_type == "fuzzy" else value, value, False, suggestion


def build_vocab_hints(vocabularies: dict[str, Vocabulary]) -> str:
    """Build a combined vocab hints block for use as ``{{ vocab_hints }}`` in templates."""
    if not vocabularies:
        return ""
    sections = []
    for vocab in vocabularies.values():
        if vocab.inject_prompt:
            sections.append(vocab.build_prompt_suffix())
    if not sections:
        return ""
    return "---\nVocabulary constraints:\n" + "\n\n".join(sections)
