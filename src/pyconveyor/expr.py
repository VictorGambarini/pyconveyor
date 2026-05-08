"""Constrained expression evaluator with AST whitelist.

Only the following node types are permitted in expressions:
- Attribute access  (steps.extract.primary)
- Item lookup       (ctx["key"])
- Boolean operators (and, or, not)
- Comparison ops    (==, !=, is, is not, in, not in, <, <=, >, >=)
- Ternary           (x if cond else y)
- String / numeric / bool / None literals
- Calls to an explicit allowlist: first_non_none, active_models, len
- Tuple / List literals (for 'in' checks against literals)

Any expression with a disallowed AST node raises ExpressionSecurityError at
pipeline load time — before any run begins.
"""
from __future__ import annotations

import ast
import re
from typing import Any

from .errors import ExpressionEvalError, ExpressionSecurityError

# ── Allowed function names in call expressions ────────────────────────────────
_ALLOWED_CALLS: frozenset[str] = frozenset({"first_non_none", "active_models", "len"})

# ── Allowed AST node types ─────────────────────────────────────────────────────
_ALLOWED_NODES: frozenset[type] = frozenset(
    {
        ast.Expression,
        ast.Name,
        ast.Attribute,
        ast.Subscript,
        ast.BoolOp,
        ast.UnaryOp,
        ast.Compare,
        ast.IfExp,
        ast.Constant,
        ast.Load,
        ast.And,
        ast.Or,
        ast.Not,
        ast.Eq,
        ast.NotEq,
        ast.Is,
        ast.IsNot,
        ast.In,
        ast.NotIn,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.Call,
        ast.Tuple,
        ast.List,
        ast.Slice,
        # Python 3.8 index node (no-op in 3.9+)
        # ast.Index is removed in 3.9, conditionally included below
    }
)

# ast.Index was removed in Python 3.9
try:
    _ALLOWED_NODES = _ALLOWED_NODES | {ast.Index}  # type: ignore[attr-defined]
except AttributeError:
    pass

# ── Regex for {{ expr }} substitution ─────────────────────────────────────────
_EXPR_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.DOTALL)

# Normalise 'is not none' / 'is none' to != / == for proxy-safe evaluation
_IS_NOT_NONE_RE = re.compile(r"\bis\s+not\s+none\b", re.IGNORECASE)
_IS_NONE_RE = re.compile(r"\bis\s+none\b", re.IGNORECASE)
_IS_NOT_RE = re.compile(r"\bis\s+not\b(?!\s+none\b)", re.IGNORECASE)
_IS_RE = re.compile(r"\bis\b(?!\s+not\b)", re.IGNORECASE)


def _normalise_is(expr: str) -> str:
    """Rewrite 'is not none' / 'is none' to '!= None' / '== None'."""
    expr = _IS_NOT_NONE_RE.sub("!= None", expr)
    expr = _IS_NONE_RE.sub("== None", expr)
    return expr


# ── AST whitelist checker ──────────────────────────────────────────────────────

def _check_node(
    node: ast.AST, expr: str, file: str | None, key_path: str | None
) -> None:
    node_type = type(node)
    if node_type not in _ALLOWED_NODES:
        raise ExpressionSecurityError(
            f"Expression contains disallowed AST node '{node_type.__name__}': {expr!r}",
            file=file,
            key_path=key_path,
        )
    if isinstance(node, ast.Call):
        func = node.func
        if not isinstance(func, ast.Name):
            raise ExpressionSecurityError(
                f"Only direct function calls are permitted (not method calls or closures): "
                f"{expr!r}",
                file=file,
                key_path=key_path,
            )
        if func.id not in _ALLOWED_CALLS:
            raise ExpressionSecurityError(
                f"Call to disallowed function '{func.id}' in expression {expr!r}. "
                f"Allowed helpers: {sorted(_ALLOWED_CALLS)}",
                file=file,
                key_path=key_path,
            )
    for child in ast.iter_child_nodes(node):
        _check_node(child, expr, file, key_path)


def validate_expression(
    expr: str,
    file: str | None = None,
    key_path: str | None = None,
) -> None:
    """Parse and AST-validate an expression string.

    Raises ``ExpressionSecurityError`` if the expression uses disallowed constructs.
    Call this at pipeline load time (before any run).
    """
    normalised = _normalise_is(expr)
    try:
        tree = ast.parse(normalised, mode="eval")
    except SyntaxError as e:
        raise ExpressionSecurityError(
            f"Invalid expression syntax: {expr!r} — {e}",
            file=file,
            key_path=key_path,
        ) from e
    _check_node(tree, expr, file, key_path)


def validate_all_expressions(
    value: Any,
    file: str | None = None,
    key_path: str | None = None,
) -> None:
    """Recursively validate all ``{{ }}`` expressions found in a YAML value."""
    if isinstance(value, str):
        for m in _EXPR_RE.finditer(value):
            validate_expression(m.group(1).strip(), file=file, key_path=key_path)
    elif isinstance(value, dict):
        for k, v in value.items():
            child = f"{key_path}.{k}" if key_path else str(k)
            validate_all_expressions(v, file=file, key_path=child)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            child = f"{key_path}[{i}]" if key_path else f"[{i}]"
            validate_all_expressions(v, file=file, key_path=child)


# ── Built-in helpers available inside expressions ─────────────────────────────

def _first_non_none(*args: Any) -> Any:
    for a in args:
        v = a._unwrap() if isinstance(a, _NullSafeProxy) else a
        if v is not None:
            return a
    return None


def _active_models(models: Any) -> list[str]:
    if isinstance(models, _NullSafeProxy):
        models = models._unwrap()
    if not isinstance(models, dict):
        return []
    return [k for k, v in models.items() if v is not None]


_HELPERS: dict[str, Any] = {
    "first_non_none": _first_non_none,
    "active_models": _active_models,
    "len": len,
    "None": None,
    "True": True,
    "False": False,
    "none": None,  # lowercase alias for template convenience
    "true": True,
    "false": False,
}


# ── Expression evaluation ──────────────────────────────────────────────────────

def evaluate_expression(
    expr: str,
    context: dict[str, Any],
    file: str | None = None,
    key_path: str | None = None,
) -> Any:
    """Evaluate a pre-validated expression against a context dict.

    The context should include ``ctx`` (NullSafeProxy of input data) and
    ``steps`` (NullSafeProxy of step results dict).
    """
    normalised = _normalise_is(expr)
    namespace = {**_HELPERS, **context}
    try:
        code = compile(ast.parse(normalised, mode="eval"), "<expr>", "eval")
        return eval(code, {"__builtins__": {}}, namespace)  # noqa: S307
    except Exception as e:
        raise ExpressionEvalError(
            f"Failed to evaluate expression {expr!r}: {e}"
        ) from e


def resolve_value(
    value: Any,
    context: dict[str, Any],
    file: str | None = None,
    key_path: str | None = None,
) -> Any:
    """If *value* is a ``{{ expr }}`` string, evaluate it; otherwise return as-is.

    For strings that contain embedded expressions (not a bare ``{{ expr }}``),
    each ``{{ }}`` is resolved and converted to str and the result is assembled.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    m = _EXPR_RE.fullmatch(stripped)
    if m:
        return evaluate_expression(m.group(1).strip(), context, file, key_path)

    # Inline substitutions inside a larger string
    def _sub(match: re.Match) -> str:  # type: ignore[type-arg]
        result = evaluate_expression(match.group(1).strip(), context, file, key_path)
        if isinstance(result, _NullSafeProxy):
            result = result._unwrap()
        return str(result) if result is not None else ""

    return _EXPR_RE.sub(_sub, value)


# ── _NullSafeProxy ─────────────────────────────────────────────────────────────

class _NullSafeProxy:
    """Proxy wrapper for the ``ctx`` input dict.

    Converts ``ctx.missing_key`` → ``None`` instead of ``AttributeError``,
    so pipeline expressions don't need defensive ``if`` guards for optional
    input fields.
    """

    __slots__ = ("_v",)

    def __init__(self, value: Any) -> None:
        object.__setattr__(self, "_v", value)

    # -- internal unwrap --------------------------------------------------------
    def _unwrap(self) -> Any:
        return object.__getattribute__(self, "_v")

    # -- attribute access -------------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        v = object.__getattribute__(self, "_v")
        if v is None:
            return _NullSafeProxy(None)
        if isinstance(v, dict):
            result = v.get(name)
        else:
            result = getattr(v, name, None)
        return _NullSafeProxy(result)

    # -- item access ------------------------------------------------------------
    def __getitem__(self, key: Any) -> Any:
        v = object.__getattribute__(self, "_v")
        if v is None:
            return _NullSafeProxy(None)
        try:
            return _NullSafeProxy(v[key])
        except (KeyError, IndexError, TypeError):
            return _NullSafeProxy(None)

    # -- truthiness / comparisons ----------------------------------------------
    def __bool__(self) -> bool:
        v = object.__getattribute__(self, "_v")
        return v is not None and bool(v)

    def __eq__(self, other: object) -> bool:
        v = object.__getattribute__(self, "_v")
        if isinstance(other, _NullSafeProxy):
            other = object.__getattribute__(other, "_v")
        return v == other  # type: ignore[return-value]

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __repr__(self) -> str:
        v = object.__getattribute__(self, "_v")
        return repr(v)

    def __str__(self) -> str:
        v = object.__getattribute__(self, "_v")
        return str(v) if v is not None else ""

    def __iter__(self) -> Any:
        v = object.__getattribute__(self, "_v")
        if v is None:
            return iter([])
        return iter(v)

    def __len__(self) -> int:
        v = object.__getattribute__(self, "_v")
        if v is None:
            return 0
        return len(v)

    def __contains__(self, item: Any) -> bool:
        v = object.__getattribute__(self, "_v")
        if v is None:
            return False
        return item in v


# ── _StepsProxy ────────────────────────────────────────────────────────────────

class _StepsProxy:
    """Thin wrapper over the step-results dict enabling attribute-style access.

    ``steps.extract`` → the raw step output value (Pydantic model, dict, or None).
    ``steps.extract.primary`` → sub-attribute access on the result.

    Unlike ``_NullSafeProxy``, attribute access on a missing/None step returns
    ``None`` directly (not a proxy) so that ``is not None`` checks work correctly
    in expressions.
    """

    __slots__ = ("_d",)

    def __init__(self, data: dict[str, Any]) -> None:
        object.__setattr__(self, "_d", data)

    def __getattr__(self, name: str) -> Any:
        d = object.__getattribute__(self, "_d")
        val = d.get(name)
        if val is None:
            return None
        if isinstance(val, dict):
            return _StepsProxy(val)
        return val

    def __getitem__(self, key: str) -> Any:
        d = object.__getattribute__(self, "_d")
        return d.get(key)

    def __repr__(self) -> str:
        d = object.__getattribute__(self, "_d")
        return f"_StepsProxy({d!r})"
