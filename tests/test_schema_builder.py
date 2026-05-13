"""Tests for schema_builder: yaml_dict_to_model and model_to_schema_hint."""
from __future__ import annotations

import typing

import pytest
from pydantic import BaseModel, ValidationError

from pyconveyor.errors import SchemaRefError
from pyconveyor.schema_builder import (
    _type_to_description,
    model_to_schema_hint,
    yaml_dict_to_model,
)

# ── yaml_dict_to_model ────────────────────────────────────────────────────────

class TestYamlDictToModel:
    def test_str_field(self):
        model = yaml_dict_to_model("M", {"name": "str"})
        assert issubclass(model, BaseModel)
        m = model(name="hello")
        assert m.name == "hello"

    def test_int_field(self):
        model = yaml_dict_to_model("M", {"count": "int"})
        m = model(count=5)
        assert m.count == 5

    def test_float_field(self):
        model = yaml_dict_to_model("M", {"score": "float"})
        m = model(score=3.14)
        assert m.score == pytest.approx(3.14)

    def test_bool_field(self):
        model = yaml_dict_to_model("M", {"flag": "bool"})
        m = model(flag=True)
        assert m.flag is True

    def test_list_str_field(self):
        model = yaml_dict_to_model("M", {"tags": "list[str]"})
        m = model(tags=["a", "b"])
        assert m.tags == ["a", "b"]

    def test_list_int_field(self):
        model = yaml_dict_to_model("M", {"nums": "list[int]"})
        m = model(nums=[1, 2, 3])
        assert m.nums == [1, 2, 3]

    def test_list_float_field(self):
        model = yaml_dict_to_model("M", {"vals": "list[float]"})
        m = model(vals=[1.1, 2.2])
        assert m.vals[0] == pytest.approx(1.1)

    def test_list_bool_field(self):
        model = yaml_dict_to_model("M", {"flags": "list[bool]"})
        m = model(flags=[True, False])
        assert m.flags == [True, False]

    def test_dict_str_str_field(self):
        model = yaml_dict_to_model("M", {"meta": "dict[str, str]"})
        m = model(meta={"key": "val"})
        assert m.meta == {"key": "val"}

    def test_dict_str_int_field(self):
        model = yaml_dict_to_model("M", {"counts": "dict[str, int]"})
        m = model(counts={"a": 1})
        assert m.counts == {"a": 1}

    def test_dict_str_float_field(self):
        model = yaml_dict_to_model("M", {"scores": "dict[str, float]"})
        m = model(scores={"x": 0.5})
        assert m.scores["x"] == pytest.approx(0.5)

    def test_optional_str_field_default_none(self):
        model = yaml_dict_to_model("M", {"note": "str | None"})
        m = model()
        assert m.note is None

    def test_optional_str_not_required(self):
        model = yaml_dict_to_model("M", {"note": "str | None"})
        m = model(note="hello")
        assert m.note == "hello"

    def test_optional_int_field(self):
        model = yaml_dict_to_model("M", {"score": "int | None"})
        assert model().score is None
        assert model(score=42).score == 42

    def test_optional_list_str_field(self):
        model = yaml_dict_to_model("M", {"tags": "list[str] | None"})
        assert model().tags is None
        assert model(tags=["x"]).tags == ["x"]

    def test_optional_dict_field(self):
        model = yaml_dict_to_model("M", {"meta": "dict[str, str] | None"})
        assert model().meta is None

    def test_required_field_raises_on_missing(self):
        model = yaml_dict_to_model("M", {"name": "str"})
        with pytest.raises(ValidationError):
            model()

    def test_optional_field_not_required(self):
        model = yaml_dict_to_model("M", {"x": "str | None"})
        m = model()
        assert m.x is None

    def test_unsupported_type_raises_schema_ref_error(self):
        with pytest.raises(SchemaRefError):
            yaml_dict_to_model("M", {"ts": "datetime"})

    def test_multiple_fields(self):
        model = yaml_dict_to_model("Article", {
            "title": "str",
            "score": "int | None",
            "tags": "list[str]",
        })
        m = model(title="Hello", tags=["a"])
        assert m.title == "Hello"
        assert m.score is None
        assert m.tags == ["a"]

    def test_empty_field_map_returns_valid_model(self):
        model = yaml_dict_to_model("Empty", {})
        assert issubclass(model, BaseModel)
        m = model()
        assert m is not None

    def test_pipe_none_no_space(self):
        model = yaml_dict_to_model("M", {"x": "str|None"})
        assert model().x is None

    def test_list_unsupported_inner_type_raises(self):
        with pytest.raises(SchemaRefError):
            yaml_dict_to_model("M", {"items": "list[datetime]"})

    def test_dict_non_str_key_raises(self):
        with pytest.raises(SchemaRefError):
            yaml_dict_to_model("M", {"m": "dict[int, str]"})


# ── model_to_schema_hint ──────────────────────────────────────────────────────

class TestModelToSchemaHint:
    def test_required_fields_have_required_suffix(self):
        model = yaml_dict_to_model("M", {"title": "str", "count": "int"})
        hint = model_to_schema_hint(model)
        assert "(required)" in hint
        assert '"title": string (required)' in hint
        assert '"count": integer (required)' in hint

    def test_optional_fields_have_or_null_suffix(self):
        model = yaml_dict_to_model("M", {"note": "str | None"})
        hint = model_to_schema_hint(model)
        assert "or null" in hint
        assert "(required)" not in hint

    def test_list_str_described_as_array_of_string(self):
        model = yaml_dict_to_model("M", {"tags": "list[str]"})
        hint = model_to_schema_hint(model)
        assert "array of string" in hint

    def test_list_int_described_as_array_of_integer(self):
        model = yaml_dict_to_model("M", {"nums": "list[int]"})
        hint = model_to_schema_hint(model)
        assert "array of integer" in hint

    def test_dict_str_any_described(self):
        from typing import Any

        class WithDict(BaseModel):
            meta: dict[str, Any]  # type: ignore[type-arg]

        hint = model_to_schema_hint(WithDict)
        assert "object with any value values" in hint

    def test_none_returns_empty_string(self):
        assert model_to_schema_hint(None) == ""

    def test_non_model_returns_empty_string(self):
        assert model_to_schema_hint(str) == ""  # type: ignore[arg-type]

    def test_model_with_no_fields_returns_empty_string(self):
        class Empty(BaseModel):
            pass
        assert model_to_schema_hint(Empty) == ""

    def test_first_line_is_header(self):
        model = yaml_dict_to_model("M", {"x": "str"})
        hint = model_to_schema_hint(model)
        assert hint.startswith("Return a JSON object with the following fields:")


# ── _type_to_description edge cases ──────────────────────────────────────────

class TestTypeToDescription:
    def test_typing_any_returns_any_value(self):
        assert _type_to_description(typing.Any) == "any value"

    def test_unknown_annotation_returns_any_value(self):
        class _Exotic:
            pass
        assert _type_to_description(_Exotic) == "any value"

    def test_model_to_schema_hint_exception_guard_returns_empty(self):
        from unittest.mock import patch

        class GoodModel(BaseModel):
            x: str

        # Patch issubclass to raise, triggering the except Exception guard
        with patch("builtins.issubclass", side_effect=TypeError("simulated failure")):
            assert model_to_schema_hint(GoodModel) == ""


# ── Rich field format ─────────────────────────────────────────────────────────

class TestRichFieldFormat:
    def test_rich_type_only(self):
        model = yaml_dict_to_model("M", {"name": {"type": "str"}})
        m = model(name="hello")
        assert m.name == "hello"

    def test_rich_optional(self):
        model = yaml_dict_to_model("M", {"note": {"type": "str | None"}})
        assert model().note is None
        assert model(note="hi").note == "hi"

    def test_rich_description_stored_on_field(self):
        model = yaml_dict_to_model("M", {"title": {"type": "str", "description": "The title"}})
        assert model.model_fields["title"].description == "The title"

    def test_mixed_simple_and_rich(self):
        model = yaml_dict_to_model("M", {
            "plain": "str",
            "rich": {"type": "int | None", "description": "A number"},
        })
        m = model(plain="x")
        assert m.plain == "x"
        assert m.rich is None
        assert model.model_fields["rich"].description == "A number"

    def test_rich_missing_type_raises(self):
        from pyconveyor.errors import SchemaRefError
        with pytest.raises(SchemaRefError, match="missing the required 'type'"):
            yaml_dict_to_model("M", {"x": {"description": "no type here"}})

    def test_rich_unsupported_type_raises(self):
        from pyconveyor.errors import SchemaRefError
        with pytest.raises(SchemaRefError):
            yaml_dict_to_model("M", {"x": {"type": "datetime"}})

    def test_non_string_non_dict_spec_raises(self):
        from pyconveyor.errors import SchemaRefError
        with pytest.raises(SchemaRefError, match="must be a string or mapping"):
            yaml_dict_to_model("M", {"x": 42})


# ── Validators ────────────────────────────────────────────────────────────────

class TestValidators:
    def test_pattern_valid(self):
        model = yaml_dict_to_model("M", {
            "code": {"type": "str", "pattern": r"^[A-Z]{3}$"},
        })
        assert model(code="ABC").code == "ABC"

    def test_pattern_error_raises(self):
        from pydantic import ValidationError
        model = yaml_dict_to_model("M", {
            "code": {"type": "str", "pattern": r"^[A-Z]{3}$"},
        })
        with pytest.raises(ValidationError):
            model(code="abc")

    def test_pattern_on_fail_null(self):
        model = yaml_dict_to_model("M", {
            "code": {"type": "str | None", "pattern": r"^[A-Z]{3}$", "on_fail": "null"},
        })
        assert model(code="bad").code is None
        assert model(code="ABC").code == "ABC"

    def test_pattern_on_fail_none_treated_as_null(self):
        # YAML `on_fail: null` deserialises to Python None; should coerce to null.
        model = yaml_dict_to_model("M", {
            "code": {"type": "str | None", "pattern": r"^[A-Z]{3}$", "on_fail": None},
        })
        assert model(code="bad").code is None
        assert model(code="ABC").code == "ABC"

    def test_pattern_on_fail_warn(self, caplog):
        import logging
        model = yaml_dict_to_model("M", {
            "code": {"type": "str", "pattern": r"^[A-Z]{3}$", "on_fail": "warn"},
        })
        with caplog.at_level(logging.WARNING, logger="pyconveyor.schema"):
            m = model(code="bad")
        assert m.code == "bad"
        assert any("does not match pattern" in r.message for r in caplog.records)

    def test_pattern_none_value_skipped(self):
        model = yaml_dict_to_model("M", {
            "code": {"type": "str | None", "pattern": r"^[A-Z]{3}$"},
        })
        assert model(code=None).code is None

    def test_min_length_valid(self):
        model = yaml_dict_to_model("M", {"name": {"type": "str", "min_length": 2}})
        assert model(name="hi").name == "hi"

    def test_min_length_error_raises(self):
        from pydantic import ValidationError
        model = yaml_dict_to_model("M", {"name": {"type": "str", "min_length": 2}})
        with pytest.raises(ValidationError):
            model(name="x")

    def test_max_length_error_raises(self):
        from pydantic import ValidationError
        model = yaml_dict_to_model("M", {"name": {"type": "str", "max_length": 3}})
        with pytest.raises(ValidationError):
            model(name="toolong")

    def test_min_length_on_fail_null(self):
        model = yaml_dict_to_model("M", {
            "name": {"type": "str | None", "min_length": 2, "on_fail": "null"},
        })
        assert model(name="x").name is None
        assert model(name="ok").name == "ok"

    def test_min_items_valid(self):
        model = yaml_dict_to_model("M", {
            "tags": {"type": "list", "items": "str", "min_items": 1},
        })
        assert model(tags=["a"]).tags == ["a"]

    def test_min_items_error_raises(self):
        from pydantic import ValidationError
        model = yaml_dict_to_model("M", {
            "tags": {"type": "list", "items": "str", "min_items": 1},
        })
        with pytest.raises(ValidationError):
            model(tags=[])

    def test_max_items_error_raises(self):
        from pydantic import ValidationError
        model = yaml_dict_to_model("M", {
            "tags": {"type": "list", "items": "str", "max_items": 2},
        })
        with pytest.raises(ValidationError):
            model(tags=["a", "b", "c"])

    def test_min_items_on_fail_null(self):
        model = yaml_dict_to_model("M", {
            "tags": {"type": "list | None", "items": "str", "min_items": 1, "on_fail": "null"},
        })
        assert model(tags=[]).tags is None

    def test_multiple_validators_on_different_fields(self):
        from pydantic import ValidationError
        model = yaml_dict_to_model("M", {
            "code": {"type": "str", "pattern": r"^[A-Z]+$"},
            "name": {"type": "str", "min_length": 2},
        })
        assert model(code="ABC", name="hi").code == "ABC"
        with pytest.raises(ValidationError):
            model(code="abc", name="hi")
        with pytest.raises(ValidationError):
            model(code="ABC", name="x")


# ── Nested schemas ────────────────────────────────────────────────────────────

class TestNestedSchemas:
    def test_list_of_objects(self):
        model = yaml_dict_to_model("M", {
            "items": {
                "type": "list",
                "items": {
                    "name": {"type": "str"},
                    "value": {"type": "float"},
                },
            },
        })
        m = model(items=[{"name": "x", "value": 1.5}])
        assert m.items[0].name == "x"
        assert m.items[0].value == pytest.approx(1.5)

    def test_list_of_objects_with_primitive_items(self):
        model = yaml_dict_to_model("M", {
            "tags": {"type": "list", "items": "str"},
        })
        assert model(tags=["a", "b"]).tags == ["a", "b"]

    def test_optional_list_of_objects(self):
        model = yaml_dict_to_model("M", {
            "items": {
                "type": "list | None",
                "items": {"name": {"type": "str"}},
            },
        })
        assert model().items is None
        assert model(items=[{"name": "x"}]).items[0].name == "x"

    def test_nested_field_descriptions_preserved(self):
        model = yaml_dict_to_model("M", {
            "entries": {
                "type": "list",
                "items": {
                    "title": {"type": "str", "description": "The title"},
                },
            },
        })
        # Get the item model from the list annotation
        from typing import get_args
        item_cls = get_args(model.model_fields["entries"].annotation)[0]
        assert item_cls.model_fields["title"].description == "The title"

    def test_nested_validators_enforced(self):
        from pydantic import ValidationError
        model = yaml_dict_to_model("M", {
            "entries": {
                "type": "list",
                "items": {
                    "code": {"type": "str", "pattern": r"^[A-Z]+$"},
                },
            },
        })
        with pytest.raises(ValidationError):
            model(entries=[{"code": "bad"}])

    def test_list_items_unsupported_primitive_raises(self):
        from pyconveyor.errors import SchemaRefError
        with pytest.raises(SchemaRefError, match="unsupported items type"):
            yaml_dict_to_model("M", {
                "tags": {"type": "list", "items": "datetime"},
            })

    def test_list_items_invalid_type_raises(self):
        from pyconveyor.errors import SchemaRefError
        with pytest.raises(SchemaRefError):
            yaml_dict_to_model("M", {
                "tags": {"type": "list", "items": 42},
            })


# ── schema_hint with descriptions and nesting ─────────────────────────────────

class TestSchemaHintDescriptions:
    def test_description_appears_indented(self):
        model = yaml_dict_to_model("M", {
            "title": {"type": "str", "description": "The paper title"},
        })
        hint = model_to_schema_hint(model)
        lines = hint.splitlines()
        title_line = next(ln for ln in lines if '"title"' in ln)
        idx = lines.index(title_line)
        assert lines[idx + 1].strip() == "The paper title"
        assert lines[idx + 1].startswith("    ")  # indented

    def test_field_without_description_has_no_extra_line(self):
        model = yaml_dict_to_model("M", {"title": "str", "score": "int"})
        hint = model_to_schema_hint(model)
        lines = hint.splitlines()
        # Only header + 2 field lines, no description lines
        assert len(lines) == 3

    def test_nested_model_expands_in_hint(self):
        model = yaml_dict_to_model("M", {
            "entries": {
                "type": "list",
                "items": {
                    "name": {"type": "str", "description": "Item name"},
                    "value": {"type": "float"},
                },
            },
        })
        hint = model_to_schema_hint(model)
        assert '"entries": array of objects' in hint
        assert '"name": string' in hint
        assert "Item name" in hint
        assert '"value": number' in hint

    def test_nested_fields_more_indented_than_parent(self):
        model = yaml_dict_to_model("M", {
            "entries": {
                "type": "list",
                "items": {"name": {"type": "str", "description": "Name"}},
            },
        })
        hint = model_to_schema_hint(model)
        lines = hint.splitlines()
        entries_line = next(ln for ln in lines if '"entries"' in ln)
        name_line = next(ln for ln in lines if '"name"' in ln)
        assert len(name_line) - len(name_line.lstrip()) > len(entries_line) - len(entries_line.lstrip())

    def test_external_pydantic_model_with_field_description(self):
        from pydantic import Field
        class Annotated(BaseModel):
            organism: str = Field(..., description="Scientific name")
            score: float = Field(0.9)

        hint = model_to_schema_hint(Annotated)
        assert '"organism": string (required)' in hint
        lines = hint.splitlines()
        org_line = next(ln for ln in lines if '"organism"' in ln)
        idx = lines.index(org_line)
        assert "Scientific name" in lines[idx + 1]

    def test_hint_type_for_nested_list_is_array_of_objects(self):
        model = yaml_dict_to_model("M", {
            "items": {
                "type": "list",
                "items": {"x": {"type": "str"}},
            },
        })
        hint = model_to_schema_hint(model)
        assert "array of objects" in hint


# ── Vocab in YAML schemas ─────────────────────────────────────────────────────


class TestVocabInSchemas:
    def test_inline_vocab_stored_in_json_schema_extra(self):
        model = yaml_dict_to_model("M", {
            "plastic": {
                "type": "str",
                "vocab": {"known": ["PET", "PE"], "label": "plastic_type"},
            },
        })
        extra = model.model_fields["plastic"].json_schema_extra or {}
        vocab = extra.get("_pyconveyor_vocab")
        from pyconveyor.vocab import Vocabulary
        assert isinstance(vocab, Vocabulary)
        assert vocab.known == {"PET", "PE"}
        assert vocab.label == "plastic_type"

    def test_inline_vocab_label_defaults_to_field_name(self):
        model = yaml_dict_to_model("M", {
            "color": {
                "type": "str",
                "vocab": {"known": ["red", "green"]},
            },
        })
        extra = model.model_fields["color"].json_schema_extra or {}
        vocab = extra.get("_pyconveyor_vocab")
        assert vocab.label == "color"

    def test_inline_vocab_normalizes_value(self):
        model = yaml_dict_to_model("M", {
            "plastic": {
                "type": "str",
                "vocab": {"known": ["PET", "PE"]},
            },
        })
        # "pet" should be normalised to "PET" by the model validator
        m = model(plastic="pet")
        assert m.plastic == "PET"

    def test_inline_vocab_exact_match_passes_through(self):
        model = yaml_dict_to_model("M", {
            "plastic": {
                "type": "str",
                "vocab": {"known": ["PET", "PE"]},
            },
        })
        m = model(plastic="PE")
        assert m.plastic == "PE"

    def test_inline_vocab_novel_value_passes_through_unchanged(self):
        model = yaml_dict_to_model("M", {
            "plastic": {
                "type": "str",
                "vocab": {"known": ["PET"]},
            },
        })
        m = model(plastic="HDPE")
        assert m.plastic == "HDPE"

    def test_inline_vocab_fuzzy_match_normalizes(self):
        model = yaml_dict_to_model("M", {
            "fruit": {
                "type": "str",
                "vocab": {"known": ["banana_fruit"]},
            },
        })
        # "banana" should fuzzy-match to "banana_fruit"
        m = model(fruit="banana")
        assert m.fruit == "banana_fruit"

    def test_empty_string_not_normalized_by_vocab(self):
        """Empty strings must not be fuzzy-matched to a random vocab term."""
        model = yaml_dict_to_model("M", {
            "fruit": {
                "type": "str",
                "vocab": {"known": ["banana_fruit", "apple_fruit"]},
            },
        })
        m = model(fruit="")
        assert m.fruit == ""

    def test_vocab_ref_resolved_from_vocabularies(self):
        from pyconveyor.vocab import Vocabulary
        vocab = Vocabulary(known={"PET", "PE"}, label="plastic")
        model = yaml_dict_to_model("M", {
            "plastic": {"type": "str", "vocab": "plastic"},
        }, vocabularies={"plastic": vocab})
        extra = model.model_fields["plastic"].json_schema_extra or {}
        resolved = extra.get("_pyconveyor_vocab")
        assert resolved is vocab

    def test_vocab_ref_missing_raises(self):
        from pyconveyor.errors import SchemaRefError
        with pytest.raises(SchemaRefError, match="not found"):
            yaml_dict_to_model("M", {
                "plastic": {"type": "str", "vocab": "nonexistent"},
            }, vocabularies={})

    def test_vocab_and_validators_work_together(self):
        """Vocab normalisation runs before constraint checks."""
        model = yaml_dict_to_model("M", {
            "code": {
                "type": "str",
                "vocab": {"known": ["ABC", "XYZ"]},
                "pattern": r"^[A-Z]{3}$",
            },
        })
        # "abc" normalises to "ABC" (via vocab), then matches pattern
        m = model(code="abc")
        assert m.code == "ABC"

    def test_inline_vocab_growth_policy_must_be_auto(self):
        from pyconveyor.errors import SchemaRefError
        with pytest.raises(SchemaRefError, match="growth_policy"):
            yaml_dict_to_model("M", {
                "plastic": {
                    "type": "str",
                    "vocab": {"known": ["PET"], "growth_policy": "human"},
                },
            })

    def test_inline_vocab_no_persist(self):
        from pyconveyor.errors import SchemaRefError
        with pytest.raises(SchemaRefError, match="persist"):
            yaml_dict_to_model("M", {
                "plastic": {
                    "type": "str",
                    "vocab": {"known": ["PET"], "persist": True},
                },
            })

    def test_vocab_with_description_stored(self):
        model = yaml_dict_to_model("M", {
            "plastic": {
                "type": "str",
                "vocab": {
                    "known": ["PET", "PE"],
                    "description": "ISO 1043 resin codes",
                },
            },
        })
        extra = model.model_fields["plastic"].json_schema_extra or {}
        vocab = extra.get("_pyconveyor_vocab")
        assert vocab.description == "ISO 1043 resin codes"

    def test_mixed_vocab_and_non_vocab_fields(self):
        model = yaml_dict_to_model("M", {
            "name": "str",
            "plastic": {
                "type": "str",
                "vocab": {"known": ["PET"]},
            },
            "quantity": "int",
        })
        m = model(name="test", plastic="pet", quantity=5)
        assert m.name == "test"
        assert m.plastic == "PET"
        assert m.quantity == 5

    def test_nested_schema_with_vocab_in_item(self):
        model = yaml_dict_to_model("M", {
            "entries": {
                "type": "list",
                "items": {
                    "code": {
                        "type": "str",
                        "vocab": {"known": ["ABC", "XYZ"]},
                    },
                },
            },
        })
        m = model(entries=[{"code": "abc"}])
        assert m.entries[0].code == "ABC"

    def test_vocab_with_capture_ideal_stored(self):
        model = yaml_dict_to_model("M", {
            "plastic": {
                "type": "str",
                "vocab": {"known": ["PET"], "capture_ideal": True},
            },
        })
        extra = model.model_fields["plastic"].json_schema_extra or {}
        vocab = extra.get("_pyconveyor_vocab")
        assert vocab.capture_ideal is True

    def test_vocab_ref_removed_after_resolution(self):
        from pyconveyor.vocab import Vocabulary
        vocab = Vocabulary(known={"PET"}, label="plastic")
        model = yaml_dict_to_model("M", {
            "plastic": {"type": "str", "vocab": "plastic"},
        }, vocabularies={"plastic": vocab})
        extra = model.model_fields["plastic"].json_schema_extra or {}
        assert "_pyconveyor_vocab_ref" not in extra
        assert "_pyconveyor_vocab" in extra
