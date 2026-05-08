"""Mermaid DAG visualisation for pipeline YAML files."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def generate_mermaid(pipeline_path: str | Path) -> str:
    """Generate a Mermaid flowchart from a pipeline YAML file.

    Args:
        pipeline_path: Path to the pipeline YAML.

    Returns:
        Mermaid diagram as a string (suitable for embedding in Markdown).
    """
    path = Path(pipeline_path)
    with path.open(encoding="utf-8") as fh:
        spec: dict[str, Any] = yaml.safe_load(fh) or {}

    steps: list[dict[str, Any]] = spec.get("steps", [])
    lines: list[str] = ["flowchart TD"]

    _add_steps(lines, steps, parent=None)

    return "\n".join(lines) + "\n"


def _sanitise(name: str) -> str:
    """Make a step name safe for Mermaid node IDs."""
    return name.replace(" ", "_").replace("-", "_").replace(".", "_")


def _label(step: dict[str, Any]) -> str:
    stype = step.get("type", "llm")
    name = step.get("name", "?")
    model = step.get("model", "")
    schema = step.get("schema", "")
    fn = step.get("fn", "")
    parts = [f"<b>{name}</b>", f"<i>{stype}</i>"]
    if model:
        parts.append(f"model: {model}")
    if schema:
        short = schema.rsplit(":", 1)[-1] if ":" in schema else schema
        parts.append(f"schema: {short}")
    if fn:
        short_fn = fn.rsplit(":", 1)[-1] if ":" in fn else fn
        parts.append(f"fn: {short_fn}")
    return "<br/>".join(parts)


def _node_shape(step: dict[str, Any]) -> tuple[str, str]:
    """Return (open, close) bracket characters for Mermaid node shape."""
    stype = step.get("type", "llm")
    shapes = {
        "llm": ("[", "]"),
        "transform": ("([", "])"),
        "io": ("{", "}"),
        "validate": ("{{", "}}"),
        "parallel": ("[(", ")]"),
        "condition": ("{", "}"),
    }
    return shapes.get(stype, ("[", "]"))


def _add_steps(
    lines: list[str],
    steps: list[dict[str, Any]],
    parent: str | None,
    prefix: str = "    ",
) -> str | None:
    """Recursively add step nodes and edges.  Returns last node name."""
    prev: str | None = parent
    for step in steps:
        stype = step.get("type", "llm")
        name = step.get("name", "step")
        node_id = _sanitise(name)
        lbl = _label(step)
        open_b, close_b = _node_shape(step)

        lines.append(f'{prefix}{node_id}{open_b}"{lbl}"{close_b}')
        if prev:
            lines.append(f"{prefix}{prev} --> {node_id}")

        if stype == "parallel":
            child_steps: list[dict[str, Any]] = step.get("steps", [])
            subgraph_id = f"sub_{node_id}"
            lines.append(f"{prefix}subgraph {subgraph_id}[parallel: {name}]")
            last_children: list[str] = []
            for child in child_steps:
                last = _add_steps(lines, [child], parent=None, prefix=prefix + "    ")
                if last:
                    last_children.append(last)
            lines.append(f"{prefix}end")
            # Edge from parent to subgraph node
            if prev:
                # already added above
                pass
            prev = node_id

        elif stype == "condition":
            then_branch = step.get("then")
            else_branch = step.get("else")
            if then_branch:
                then_steps = then_branch if isinstance(then_branch, list) else [then_branch]
                last_then = _add_steps(lines, then_steps, parent=node_id, prefix=prefix)
            if else_branch:
                else_steps = else_branch if isinstance(else_branch, list) else [else_branch]
                last_else = _add_steps(lines, else_steps, parent=node_id, prefix=prefix)
            prev = node_id
        else:
            prev = node_id

    return prev
