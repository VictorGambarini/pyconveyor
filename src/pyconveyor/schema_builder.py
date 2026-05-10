"""Convert a YAML field-map into a Pydantic BaseModel class."""
from __future__ import annotations

from typing import Any, Union, get_args, get_origin

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


def yaml_dict_to_model(name: str, field_map: dict[str, str]) -> type:
    """Build and return a pydantic.BaseModel subclass from a {field: type_str} dict.

    Args:
        name: Class name for the generated model (used in error messages).
        field_map: Mapping of field name -> type string as written in YAML.

    Returns:
        A new type that is a subclass of pydantic.BaseModel.

    Raises:
        SchemaRefError: If any type string cannot be parsed.
    """
    from pydantic import create_model

    from .errors import SchemaRefError

    field_defs: dict[str, tuple[type, Any]] = {}
    for field_name, type_str in field_map.items():
        try:
            python_type, default = _parse_type(type_str)
        except SchemaRefError:
            raise SchemaRefError(
                f"Unsupported type '{type_str}' for field '{field_name}'. "
                "Use a Pydantic model in schemas.py for complex types.",
            )
        field_defs[field_name] = (python_type, default)

    return create_model(name, **field_defs)  # type: ignore[call-overload, no-any-return]


def _is_union_type(annotation: Any) -> bool:
    """Return True for both typing.Union and Python 3.10+ X|Y union types."""
    import types as _types

    return get_origin(annotation) is Union or isinstance(annotation, _types.UnionType)


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


def model_to_schema_hint(model_cls: type | None) -> str:
    """Return a plain-English prompt hint describing the fields of *model_cls*.

    The first line is always:
        Return a JSON object with the following fields:

    Each subsequent line is:
        - "field_name": <type description> (required)    # for required fields
        - "field_name": <type description> or null       # for Optional fields

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
    for fname, field_info in fields.items():
        annotation = field_info.annotation
        type_desc = _type_to_description(annotation)
        if field_info.is_required():
            lines.append(f'- "{fname}": {type_desc} (required)')
        else:
            lines.append(f'- "{fname}": {type_desc} or null')

    return "\n".join(lines)
