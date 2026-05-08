"""Tests for the AST-whitelisted expression evaluator."""
from __future__ import annotations

import pytest

from pyconveyor.errors import ExpressionSecurityError, ExpressionEvalError
from pyconveyor.expr import (
    _NullSafeProxy,
    _StepsProxy,
    evaluate_expression,
    resolve_value,
    validate_expression,
    validate_all_expressions,
)


# ── validate_expression ────────────────────────────────────────────────────────

class TestValidateExpression:
    def test_simple_attribute_access(self):
        validate_expression("ctx.document")

    def test_nested_attribute_access(self):
        validate_expression("steps.extract.primary")

    def test_comparison(self):
        validate_expression("ctx.score == 1")

    def test_boolean_operator(self):
        validate_expression("ctx.a and ctx.b")

    def test_ternary(self):
        validate_expression("ctx.x if ctx.x is not none else 0")

    def test_allowed_call_len(self):
        validate_expression("len(ctx.items)")

    def test_allowed_call_first_non_none(self):
        validate_expression("first_non_none(steps.a, steps.b)")

    def test_string_literal(self):
        validate_expression('"hello"')

    def test_numeric_literal(self):
        validate_expression("42")

    def test_none_literal(self):
        validate_expression("None")

    def test_in_operator(self):
        validate_expression("ctx.x in [1, 2, 3]")

    def test_disallowed_import(self):
        with pytest.raises(ExpressionSecurityError, match="disallowed function"):
            validate_expression("__import__('os')")

    def test_disallowed_lambda(self):
        with pytest.raises(ExpressionSecurityError):
            validate_expression("lambda x: x")

    def test_disallowed_call_to_unknown_function(self):
        with pytest.raises(ExpressionSecurityError, match="disallowed function"):
            validate_expression("eval('1+1')")

    def test_disallowed_call_to_attribute(self):
        with pytest.raises(ExpressionSecurityError, match="direct function calls"):
            validate_expression("ctx.do_something()")

    def test_disallowed_list_comp(self):
        with pytest.raises(ExpressionSecurityError):
            validate_expression("[x for x in ctx.items]")

    def test_syntax_error(self):
        with pytest.raises(ExpressionSecurityError, match="syntax"):
            validate_expression("ctx.(")

    def test_is_not_none_normalised(self):
        # 'is not none' should be normalised and not raise
        validate_expression("steps.extract is not none")

    def test_is_none_normalised(self):
        validate_expression("ctx.value is none")


# ── evaluate_expression ────────────────────────────────────────────────────────

class TestEvaluateExpression:
    def _ctx(self, **kwargs):
        return {
            "ctx": _NullSafeProxy(kwargs),
            "steps": _StepsProxy({}),
        }

    def test_attribute_access(self):
        result = evaluate_expression("ctx.name", self._ctx(name="Ada"))
        assert str(result) == "Ada"

    def test_missing_ctx_key_returns_proxy_none(self):
        result = evaluate_expression("ctx.missing", self._ctx())
        assert not bool(result)  # proxy wrapping None is falsy

    def test_comparison_true(self):
        result = evaluate_expression("ctx.x == 1", self._ctx(x=1))
        assert result is True

    def test_comparison_false(self):
        result = evaluate_expression("ctx.x == 1", self._ctx(x=2))
        assert result is False

    def test_ternary(self):
        result = evaluate_expression(
            "ctx.msg if ctx.flag else 'default'",
            self._ctx(msg="hi", flag=True),
        )
        assert result == "hi"

    def test_first_non_none_helper(self):
        steps = _StepsProxy({"a": None, "b": "found"})
        ctx = {"ctx": _NullSafeProxy({}), "steps": steps}
        result = evaluate_expression("first_non_none(steps.a, steps.b)", ctx)
        assert result == "found"

    def test_len_helper(self):
        result = evaluate_expression("len(ctx.items)", self._ctx(items=[1, 2, 3]))
        # ctx.items returns _NullSafeProxy wrapping [1,2,3]
        # The _NullSafeProxy __iter__ unwraps, but len() on proxy...
        # len on a proxy — we need to make sure it works
        assert int(str(result)) == 3 or result == 3

    def test_eval_error_on_runtime_failure(self):
        with pytest.raises(ExpressionEvalError):
            evaluate_expression("ctx.x + 1", self._ctx(x="not_a_number"))


# ── resolve_value ─────────────────────────────────────────────────────────────

class TestResolveValue:
    def _ctx(self, **kwargs):
        return {
            "ctx": _NullSafeProxy(kwargs),
            "steps": _StepsProxy({}),
        }

    def test_plain_string_unchanged(self):
        assert resolve_value("hello", self._ctx()) == "hello"

    def test_integer_unchanged(self):
        assert resolve_value(42, self._ctx()) == 42

    def test_full_expr_resolved(self):
        result = resolve_value("{{ ctx.name }}", self._ctx(name="Ada"))
        assert str(result) == "Ada"

    def test_inline_expr_in_string(self):
        result = resolve_value("Hello {{ ctx.name }}!", self._ctx(name="World"))
        assert result == "Hello World!"

    def test_none_becomes_empty_string_in_inline(self):
        result = resolve_value("Value: {{ ctx.missing }}", self._ctx())
        assert result == "Value: "


# ── _NullSafeProxy ────────────────────────────────────────────────────────────

class TestNullSafeProxy:
    def test_existing_key(self):
        p = _NullSafeProxy({"x": 42})
        assert p.x == 42

    def test_missing_key_returns_proxy_none(self):
        p = _NullSafeProxy({"x": 1})
        assert not bool(p.y)

    def test_nested_access(self):
        p = _NullSafeProxy({"a": {"b": 99}})
        assert p.a.b == 99

    def test_none_proxy_is_falsy(self):
        p = _NullSafeProxy(None)
        assert not bool(p)

    def test_equality_with_none(self):
        p = _NullSafeProxy(None)
        assert p == None  # noqa: E711

    def test_equality_with_value(self):
        p = _NullSafeProxy("hello")
        assert p == "hello"

    def test_item_access(self):
        p = _NullSafeProxy({"k": "v"})
        assert p["k"] == "v"

    def test_item_access_missing(self):
        p = _NullSafeProxy({"k": "v"})
        assert not bool(p["missing"])


# ── _StepsProxy ───────────────────────────────────────────────────────────────

class TestStepsProxy:
    def test_access_existing_step(self):
        from tests.fixtures.schemas import Greeting
        result = Greeting(message="hi", language="en")
        sp = _StepsProxy({"greet": result})
        assert sp.greet is result

    def test_access_missing_step_returns_none(self):
        sp = _StepsProxy({})
        assert sp.missing is None

    def test_access_dict_step(self):
        sp = _StepsProxy({"extract": {"primary": "value1", "reviewer": "value2"}})
        assert sp.extract.primary == "value1"

    def test_none_step_is_none(self):
        sp = _StepsProxy({"step": None})
        assert sp.step is None
