"""Tests for schema_builder: yaml_dict_to_model and model_to_schema_hint."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from pyconveyor.errors import SchemaRefError
from pyconveyor.schema_builder import model_to_schema_hint, yaml_dict_to_model


# ── yaml_dict_to_model ────────────────────────────────────────────────────────

class TestYamlDictToModel:
    def test_str_field(self):
        M = yaml_dict_to_model("M", {"name": "str"})
        assert issubclass(M, BaseModel)
        m = M(name="hello")
        assert m.name == "hello"

    def test_int_field(self):
        M = yaml_dict_to_model("M", {"count": "int"})
        m = M(count=5)
        assert m.count == 5

    def test_float_field(self):
        M = yaml_dict_to_model("M", {"score": "float"})
        m = M(score=3.14)
        assert m.score == pytest.approx(3.14)

    def test_bool_field(self):
        M = yaml_dict_to_model("M", {"flag": "bool"})
        m = M(flag=True)
        assert m.flag is True

    def test_list_str_field(self):
        M = yaml_dict_to_model("M", {"tags": "list[str]"})
        m = M(tags=["a", "b"])
        assert m.tags == ["a", "b"]

    def test_list_int_field(self):
        M = yaml_dict_to_model("M", {"nums": "list[int]"})
        m = M(nums=[1, 2, 3])
        assert m.nums == [1, 2, 3]

    def test_list_float_field(self):
        M = yaml_dict_to_model("M", {"vals": "list[float]"})
        m = M(vals=[1.1, 2.2])
        assert m.vals[0] == pytest.approx(1.1)

    def test_list_bool_field(self):
        M = yaml_dict_to_model("M", {"flags": "list[bool]"})
        m = M(flags=[True, False])
        assert m.flags == [True, False]

    def test_dict_str_str_field(self):
        M = yaml_dict_to_model("M", {"meta": "dict[str, str]"})
        m = M(meta={"key": "val"})
        assert m.meta == {"key": "val"}

    def test_dict_str_int_field(self):
        M = yaml_dict_to_model("M", {"counts": "dict[str, int]"})
        m = M(counts={"a": 1})
        assert m.counts == {"a": 1}

    def test_dict_str_float_field(self):
        M = yaml_dict_to_model("M", {"scores": "dict[str, float]"})
        m = M(scores={"x": 0.5})
        assert m.scores["x"] == pytest.approx(0.5)

    def test_optional_str_field_default_none(self):
        M = yaml_dict_to_model("M", {"note": "str | None"})
        m = M()
        assert m.note is None

    def test_optional_str_not_required(self):
        M = yaml_dict_to_model("M", {"note": "str | None"})
        m = M(note="hello")
        assert m.note == "hello"

    def test_optional_int_field(self):
        M = yaml_dict_to_model("M", {"score": "int | None"})
        assert M().score is None
        assert M(score=42).score == 42

    def test_optional_list_str_field(self):
        M = yaml_dict_to_model("M", {"tags": "list[str] | None"})
        assert M().tags is None
        assert M(tags=["x"]).tags == ["x"]

    def test_optional_dict_field(self):
        M = yaml_dict_to_model("M", {"meta": "dict[str, str] | None"})
        assert M().meta is None

    def test_required_field_raises_on_missing(self):
        M = yaml_dict_to_model("M", {"name": "str"})
        with pytest.raises(ValidationError):
            M()

    def test_optional_field_not_required(self):
        M = yaml_dict_to_model("M", {"x": "str | None"})
        # Should not raise
        m = M()
        assert m.x is None

    def test_unsupported_type_raises_schema_ref_error(self):
        with pytest.raises(SchemaRefError):
            yaml_dict_to_model("M", {"ts": "datetime"})

    def test_multiple_fields(self):
        M = yaml_dict_to_model("Article", {
            "title": "str",
            "score": "int | None",
            "tags": "list[str]",
        })
        m = M(title="Hello", tags=["a"])
        assert m.title == "Hello"
        assert m.score is None
        assert m.tags == ["a"]

    def test_empty_field_map_returns_valid_model(self):
        M = yaml_dict_to_model("Empty", {})
        assert issubclass(M, BaseModel)
        m = M()
        assert m is not None

    def test_pipe_none_no_space(self):
        M = yaml_dict_to_model("M", {"x": "str|None"})
        assert M().x is None


# ── model_to_schema_hint ──────────────────────────────────────────────────────

class TestModelToSchemaHint:
    def test_required_fields_have_required_suffix(self):
        M = yaml_dict_to_model("M", {"title": "str", "count": "int"})
        hint = model_to_schema_hint(M)
        assert "(required)" in hint
        assert '"title": string (required)' in hint
        assert '"count": integer (required)' in hint

    def test_optional_fields_have_or_null_suffix(self):
        M = yaml_dict_to_model("M", {"note": "str | None"})
        hint = model_to_schema_hint(M)
        assert "or null" in hint
        assert "(required)" not in hint

    def test_list_str_described_as_array_of_string(self):
        M = yaml_dict_to_model("M", {"tags": "list[str]"})
        hint = model_to_schema_hint(M)
        assert "array of string" in hint

    def test_list_int_described_as_array_of_integer(self):
        M = yaml_dict_to_model("M", {"nums": "list[int]"})
        hint = model_to_schema_hint(M)
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
        M = yaml_dict_to_model("M", {"x": "str"})
        hint = model_to_schema_hint(M)
        assert hint.startswith("Return a JSON object with the following fields:")
