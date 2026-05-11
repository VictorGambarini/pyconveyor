"""Convert a YAML field-map into a Pydantic BaseModel class."""
from __future__ import annotations

import logging
import re as _re
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger("pyconveyor.schema")

_PRIMITIVES: dict[str, type] = {"str": str, "int": int, "float": float, "bool": bool}


def _parse_base_type(ts: str) -> type | None:
    """Return a Python type for a base type string, or None if unsupported."""
    if ts in _PRIMITIVES:
        return _PRIMITIVES[ts]

    if ts.startswith("list[") and ts.endswith("]"):
        inner = ts[5:-1].strip()
        if inner in _PRIMITIVES:
            return list[_PRIMITIVES[inner]]  # type: ignore[valid-type]
        return None

    if ts.startswith("dict[") and ts.endswith("]"):
        inner = ts[5:-1].strip()
        parts = [p.strip() for p in inner.split(",", 1)]
        if len(parts) == 2 and parts[0] == "str" and parts[1] in _PRIMITIVES:
            return dict[str, _PRIMITIVES[parts[1]]]  # type: ignore[valid-type]
        return None

    return None


def _parse_type(type_str: str) -> tuple[type, Any]:
    """Return (python_type, default_value) for a YAML type string.

    default_value is ... (required) for non-Optional types and None for T | None.
    Raises SchemaRefError for unrecognised type strings.
    """
    from .errors import SchemaRefError

    ts = type_str.strip()
    optional = False

    if ts.endswith("| None"):
        optional = True
        ts = ts[: -len("| None")].strip()
    elif ts.endswith("|None"):
        optional = True
        ts = ts[: -len("|None")].strip()

    base = _parse_base_type(ts)
    if base is None:
        raise SchemaRefError(
            f"Unsupported type '{type_str}'. "
            "Use a Pydantic model in schemas.py for complex types.",
        )

    if optional:
        return base | None, None  # type: ignore[return-value]
    return base, ...


def _make_validator(field_rules: dict[str, dict[str, Any]]) -> Any | None:
    """Build a ``model_validator(mode='before')`` that enforces field-level rules.

    field_rules maps field name to a dict of constraint keys:
    ``pattern``, ``min_length``, ``max_length``, ``min_items``, ``max_items``, ``on_fail``.

    Returns None when there are no rules to enforce.
    """
    if not field_rules:
        return None

    from pydantic import model_validator

    _rules = dict(field_rules)  # capture by value

    def _check(cls: Any, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        for fname, rules in _rules.items():
            _raw_on_fail = rules.get("on_fail", "error")
            # YAML `on_fail: null` deserialises to Python None; treat as "null".
            on_fail: str = "null" if _raw_on_fail is None else str(_raw_on_fail)

            def _apply(msg: str, _fname: str = fname, _on_fail: str = on_fail) -> bool:
                """Coerce / warn / raise. Returns True if the field was nulled."""
                if _on_fail == "null":
                    data[_fname] = None
                    return True
                if _on_fail == "warn":
                    logger.warning("pyconveyor schema: field %r: %s — keeping value", _fname, msg)
                    return False
                raise ValueError(f"Field '{_fname}': {msg}")

            v = data.get(fname)

            # ── pattern ───────────────────────────────────────────────────────
            pat: str | None = rules.get("pattern")
            if pat is not None and v is not None:
                if not _re.match(pat, str(v)):
                    if _apply(f"{v!r} does not match pattern {pat!r}"):
                        continue

            v = data.get(fname)  # re-read; may have been nulled

            # ── min / max length (strings only) ───────────────────────────────
            min_l: int | None = rules.get("min_length")
            max_l: int | None = rules.get("max_length")
            if v is not None and isinstance(v, str) and (min_l is not None or max_l is not None):
                if min_l is not None and len(v) < min_l:
                    if _apply(f"length {len(v)} < min_length {min_l}"):
                        continue
                v = data.get(fname)
                if v is not None and isinstance(v, str) and max_l is not None and len(v) > max_l:
                    if _apply(f"length {len(v)} > max_length {max_l}"):
                        continue

            v = data.get(fname)

            # ── min / max items (lists only) ──────────────────────────────────
            min_i: int | None = rules.get("min_items")
            max_i: int | None = rules.get("max_items")
            if isinstance(v, list) and (min_i is not None or max_i is not None):
                if min_i is not None and len(v) < min_i:
                    if _apply(f"{len(v)} items < min_items {min_i}"):
                        continue
                v = data.get(fname)
                if isinstance(v, list) and max_i is not None and len(v) > max_i:
                    _apply(f"{len(v)} items > max_items {max_i}")

        return data

    return model_validator(mode="before")(classmethod(_check))  # type: ignore[arg-type]


def _parse_rich_field(
    name: str,
    field_def: dict[str, Any],
    parent_name: str,
) -> tuple[type, Any, dict[str, Any]]:
    """Parse a rich field definition dict.

    Returns ``(python_type, pydantic_field_info, validation_rules)`` where
    ``validation_rules`` is a dict suitable for passing to :func:`_make_validator`.
    """
    from pydantic import Field

    from .errors import SchemaRefError

    type_str: str | None = field_def.get("type")
    if type_str is None:
        raise SchemaRefError(f"Schema field '{name}' is missing the required 'type' key.")

    description: str | None = field_def.get("description")
    items: Any = field_def.get("items")  # str (primitive) | dict (sub-schema) | None

    # Determine whether this is a bare "list" needing an items: block
    _ts = type_str.strip()
    _bare = _ts.rstrip("| None").rstrip("|None").strip()
    optional = _ts.endswith(("| None", "|None"))

    if _bare == "list" and items is not None:
        if isinstance(items, dict):
            # list of sub-objects — recurse
            sub_model = yaml_dict_to_model(f"{parent_name}_{name}_item", items)
            base_type: type = list[sub_model]  # type: ignore[valid-type]
        elif isinstance(items, str):
            inner = _PRIMITIVES.get(items)
            if inner is None:
                raise SchemaRefError(f"Field '{name}': unsupported items type '{items}'.")
            base_type = list[inner]  # type: ignore[valid-type]
        else:
            raise SchemaRefError(
                f"Field '{name}': 'items' must be a type string or a field map, "
                f"got {type(items).__name__}."
            )
        python_type: type = (base_type | None) if optional else base_type  # type: ignore[assignment]
        default: Any = None if optional else ...
    else:
        try:
            python_type, default = _parse_type(type_str)
        except Exception:
            from .errors import SchemaRefError

            raise SchemaRefError(f"Unsupported type '{type_str}' for field '{name}'.")

    # Build Pydantic FieldInfo
    field_kwargs: dict[str, Any] = {}
    if description is not None:
        field_kwargs["description"] = description
    field_info = Field(default, **field_kwargs)

    # Collect validation rules (passed later to _make_validator)
    rules: dict[str, Any] = {}
    for key in ("pattern", "min_length", "max_length", "min_items", "max_items", "on_fail"):
        if key in field_def:
            rules[key] = field_def[key]

    return python_type, field_info, rules


def yaml_dict_to_model(name: str, field_map: dict[str, Any]) -> type:
    """Build and return a pydantic.BaseModel subclass from a YAML field map.

    Accepts both the simple string format and the rich dict format:

    Simple (unchanged)::

        {"title": "str", "score": "int | None"}

    Rich (new — adds description, vocab hint, and validation)::

        {
          "title": {
            "type": "str",
            "description": "The paper title",
            "min_length": 1,
          },
          "score": {
            "type": "int | None",
            "description": "Confidence score 0–100",
          },
        }

    Nested objects (list of sub-schema)::

        {
          "entries": {
            "type": "list",
            "description": "One entry per record",
            "items": {
              "name": {"type": "str", "description": "..."},
              "value": {"type": "float"},
            },
          },
        }

    Supported per-field validation keys: ``pattern``, ``min_length``, ``max_length``,
    ``min_items``, ``max_items``.  ``on_fail`` controls failure behaviour:
    ``"error"`` (default — raise, triggers retry), ``"null"`` (coerce to null silently),
    ``"warn"`` (log warning, keep value).

    Args:
        name: Class name for the generated model (used in error messages).
        field_map: Mapping of field name -> type string or field spec dict.

    Returns:
        A new type that is a subclass of pydantic.BaseModel.

    Raises:
        SchemaRefError: If any field spec cannot be parsed.
    """
    from pydantic import BaseModel, Field

    from .errors import SchemaRefError

    annotations: dict[str, Any] = {}
    namespace: dict[str, Any] = {"__annotations__": annotations}
    all_rules: dict[str, dict[str, Any]] = {}

    for field_name, field_spec in field_map.items():
        if not isinstance(field_name, str):
            raise SchemaRefError(
                f"Field name {field_name!r} is not a string. "
                "Quote YAML booleans/null like '\"yes\"', '\"true\"', '\"null\"' "
                "to use them as field names.",
            )

        if isinstance(field_spec, str):
            # Simple shorthand: field_name: "type_string"
            try:
                python_type, default = _parse_type(field_spec)
            except SchemaRefError:
                raise SchemaRefError(
                    f"Unsupported type '{field_spec}' for field '{field_name}'. "
                    "Use a Pydantic model in schemas.py for complex types.",
                )
            annotations[field_name] = python_type
            namespace[field_name] = Field(default)

        elif isinstance(field_spec, dict):
            # Rich format: field_name: {type: ..., description: ..., ...}
            python_type, field_info, rules = _parse_rich_field(field_name, field_spec, name)
            annotations[field_name] = python_type
            namespace[field_name] = field_info
            if rules:
                all_rules[field_name] = rules

        else:
            raise SchemaRefError(
                f"Field '{field_name}' spec must be a string or mapping, "
                f"got {type(field_spec).__name__}."
            )

    # Attach a combined model_validator for all field-level validation rules
    validator = _make_validator(all_rules)
    if validator is not None:
        namespace["_pyconveyor_validate"] = validator

    return type(name, (BaseModel,), namespace)


# ── Schema hint rendering ─────────────────────────────────────────────────────


def _is_union_type(annotation: Any) -> bool:
    """Return True for both typing.Union and Python 3.10+ X|Y union types."""
    import types as _types

    return get_origin(annotation) is Union or isinstance(annotation, _types.UnionType)


def _get_nested_model(annotation: Any) -> type[BaseModel] | None:
    """If annotation is list[SomeBaseModel] (or Optional thereof), return SomeBaseModel."""
    from pydantic import BaseModel

    if _is_union_type(annotation):
        for arg in get_args(annotation):
            if arg is not type(None):
                result = _get_nested_model(arg)
                if result is not None:
                    return result
        return None

    if get_origin(annotation) is list:
        args = get_args(annotation)
        if args:
            try:
                if isinstance(args[0], type) and issubclass(args[0], BaseModel):
                    return args[0]
            except TypeError:
                pass
    return None


def _type_to_description(annotation: Any) -> str:
    """Convert a Python type annotation to a human-readable string."""
    import typing as _typing

    if _is_union_type(annotation):
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _type_to_description(non_none[0])
        return "any value"

    origin = get_origin(annotation)

    if origin is list:
        args = get_args(annotation)
        if args:
            # BaseModel subclass → "array of objects" (expanded separately)
            try:
                from pydantic import BaseModel

                if isinstance(args[0], type) and issubclass(args[0], BaseModel):
                    return "array of objects"
            except (ImportError, TypeError):
                pass
            return f"array of {_type_to_description(args[0])}"
        return "array"

    if origin is dict:
        args = get_args(annotation)
        if len(args) >= 2:
            return f"object with {_type_to_description(args[1])} values"
        return "object"

    _desc = {str: "string", int: "integer", float: "number", bool: "boolean"}
    if annotation in _desc:
        return _desc[annotation]

    if annotation is _typing.Any:
        return "any value"

    return "any value"


def _render_fields(fields: dict[str, Any], indent: int = 0) -> list[str]:
    """Render field lines with optional description and nested model expansion."""
    prefix = "    " * indent
    lines: list[str] = []

    for fname, field_info in fields.items():
        annotation = field_info.annotation
        nested = _get_nested_model(annotation)
        type_desc = _type_to_description(annotation)  # handles nested → "array of objects"

        req = "(required)" if field_info.is_required() else "or null"
        lines.append(f'{prefix}- "{fname}": {type_desc} {req}')

        desc = getattr(field_info, "description", None)
        if desc:
            lines.append(f"{prefix}    {desc}")

        if nested is not None:
            try:
                lines.extend(_render_fields(nested.model_fields, indent + 1))
            except Exception:
                pass

    return lines


def model_to_schema_hint(model_cls: type | None) -> str:
    """Return a plain-English prompt hint describing the fields of *model_cls*.

    Fields with descriptions get an indented second line::

        - "field_name": string (required)
            Description text here.

    Nested models (list of objects) are expanded inline with deeper indentation::

        - "entries": array of objects (required)
            - "organism_name": string (required)
                Genus + species binomial only.

    Works with any Pydantic BaseModel, whether hand-written (using
    ``Field(description=...)``) or generated by :func:`yaml_dict_to_model`.

    Returns an empty string if *model_cls* is None or has no fields.
    """
    if model_cls is None:
        return ""

    try:
        from pydantic import BaseModel

        if not (isinstance(model_cls, type) and issubclass(model_cls, BaseModel)):
            return ""
        fields = model_cls.model_fields
        if not fields:
            return ""
    except Exception:
        return ""

    lines = ["Return a JSON object with the following fields:"]
    lines.extend(_render_fields(fields, indent=0))
    return "\n".join(lines)
