"""pyconveyor CLI — init, run, validate, schema, visualise."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    """Main CLI entry point.  Dispatched by ``pyproject.toml``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pyconveyor",
        description="Deterministic YAML pipeline engine for structured LLM extraction",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Bootstrap a new pipeline directory")
    p_init.add_argument("directory", nargs="?", default=".", help="Target directory (default: .)")

    # run
    p_run = sub.add_parser("run", help="Run a pipeline")
    p_run.add_argument("pipeline", help="Path to pipeline.yaml")
    p_run.add_argument("--input", "-i", default="-", help="Input JSON file or - for stdin")
    p_run.add_argument("--output", "-o", help="Output JSON file (default: stdout)")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--no-cache", action="store_true")
    p_run.add_argument("--refresh-cache", action="store_true")
    p_run.add_argument("--verbose", "-v", action="store_true")
    p_run.add_argument("--quiet", "-q", action="store_true")

    # validate
    p_val = sub.add_parser("validate", help="Validate a pipeline YAML")
    p_val.add_argument("pipeline", help="Path to pipeline.yaml")

    # schema
    p_schema = sub.add_parser("schema", help="Emit JSONSchema for the pipeline YAML format")
    p_schema.add_argument("--indent", type=int, default=2)

    # batch
    p_batch = sub.add_parser("batch", help="Run a pipeline over a JSONL input file")
    p_batch.add_argument("pipeline", help="Path to pipeline.yaml")
    p_batch.add_argument(
        "--input", "-i", default="-",
        help="JSONL input file (one JSON object per line) or - for stdin",
    )
    p_batch.add_argument("--output", "-o", help="Output JSONL file (default: stdout)")
    p_batch.add_argument("--workers", "-w", type=int, default=4, help="Parallel worker threads")
    p_batch.add_argument("--key", "-k", default="id", help="Field used as item identifier")
    p_batch.add_argument("--no-progress", action="store_true", help="Suppress progress bar")
    p_batch.add_argument("--no-cache", action="store_true")
    p_batch.add_argument("--dry-run", action="store_true")

    # visualise / visualize
    p_vis = sub.add_parser("visualise", aliases=["visualize"], help="Generate Mermaid DAG")
    p_vis.add_argument("pipeline", help="Path to pipeline.yaml")
    p_vis.add_argument("--output", "-o", help="Output file (default: stdout)")

    args = parser.parse_args()

    if args.command == "init":
        _cmd_init(args)
    elif args.command == "run":
        _cmd_run(args)
    elif args.command == "batch":
        _cmd_batch(args)
    elif args.command == "validate":
        _cmd_validate(args)
    elif args.command == "schema":
        _cmd_schema(args)
    elif args.command in ("visualise", "visualize"):
        _cmd_visualise(args)


# ── init ───────────────────────────────────────────────────────────────────────

def _cmd_init(args: Any) -> None:
    target = Path(args.directory)
    target.mkdir(parents=True, exist_ok=True)

    _write_template(target / "pipeline.yaml", _PIPELINE_TMPL)
    _write_template(target / "prompts" / "extract.j2", _PROMPT_TMPL)
    _write_template(target / "schemas.py", _SCHEMAS_TMPL)
    _write_template(target / "steps.py", _STEPS_TMPL)

    # .vscode/settings.json
    schema_path = target / "pyconveyor-schema.json"
    vscode_dir = target / ".vscode"
    vscode_dir.mkdir(exist_ok=True)
    _write_template(
        vscode_dir / "settings.json",
        _VSCODE_SETTINGS_TMPL.format(schema_file="pyconveyor-schema.json"),
    )

    # Export schema
    schema_doc = _pipeline_jsonschema()
    schema_path.write_text(json.dumps(schema_doc, indent=2) + "\n", encoding="utf-8")

    # .gitignore entries
    gitignore = target / ".gitignore"
    gitignore_entries = "\n.pyconveyor-cache/\n.env\n"
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8")
        if ".pyconveyor-cache" not in existing:
            with gitignore.open("a", encoding="utf-8") as fh:
                fh.write(gitignore_entries)
    else:
        gitignore.write_text(gitignore_entries.lstrip("\n"), encoding="utf-8")

    print(f"Initialised pipeline in '{target}'")
    print("  pipeline.yaml       — pipeline spec")
    print("  prompts/extract.j2  — example prompt template")
    print("  schemas.py          — example Pydantic schema")
    print("  steps.py            — example step function")
    print("  .vscode/settings.json — editor autocomplete")
    print()
    print("Next steps:")
    print(f"  cd {target}")
    print("  export OPENAI_API_KEY=sk-...")
    print("  pyconveyor run pipeline.yaml --input '{\"document\": \"your text here\"}'")


def _write_template(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding="utf-8")
        print(f"  Created: {path}")
    else:
        print(f"  Skipped (exists): {path}")


# ── run ────────────────────────────────────────────────────────────────────────

def _cmd_run(args: Any) -> None:
    import logging as _logging

    from .runner import PipelineRunner

    if args.verbose:
        _logging.getLogger("pyconveyor").setLevel(_logging.DEBUG)
    elif args.quiet:
        _logging.getLogger("pyconveyor").setLevel(_logging.ERROR)

    # Load input — inline JSON string or file path
    if args.input == "-":
        raw = sys.stdin.read()
    elif args.input.lstrip().startswith(("{", "[")):
        raw = args.input
    else:
        raw = Path(args.input).read_text(encoding="utf-8")
    try:
        input_data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: invalid input JSON: {e}", file=sys.stderr)
        sys.exit(1)

    runner = PipelineRunner(args.pipeline)
    result = runner.run(
        input_data,
        use_cache=not args.no_cache,
        refresh_cache=args.refresh_cache,
        dry_run=args.dry_run,
    )

    if result.failed:
        fs = result.failure_state
        print(
            f"Pipeline FAILED at step '{fs.step_name if fs else '?'}': "
            f"{fs.exception if fs else 'unknown'}",
            file=sys.stderr,
        )
        sys.exit(2)

    summary = result.summary()
    output: dict[str, Any] = {
        "steps": {
            name: _serialise(sr.value)
            for name, sr in result.steps.items()
        },
        "summary": {
            "steps_run": summary.steps_run,
            "steps_skipped": summary.steps_skipped,
            "llm_calls": summary.llm_calls,
            "elapsed_seconds": round(summary.elapsed_seconds, 2),
        },
    }

    out_str = json.dumps(output, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(out_str + "\n", encoding="utf-8")
        print(f"Output written to {args.output}")
    else:
        print(out_str)


def _cmd_batch(args: Any) -> None:
    from .batch import BatchRunner

    if args.input == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.input).read_text(encoding="utf-8")

    items: list[dict[str, Any]] = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON on line {lineno}: {e}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(obj, dict):
            print(f"Error: line {lineno} is not a JSON object", file=sys.stderr)
            sys.exit(1)
        items.append(obj)

    if not items:
        print("Error: no items found in input", file=sys.stderr)
        sys.exit(1)

    runner = BatchRunner(
        args.pipeline,
        max_workers=args.workers,
        progress=not args.no_progress,
    )

    output_lines: list[str] = []
    for item_id, rctx in runner.run(
        items,
        key=args.key,
        use_cache=not args.no_cache,
        dry_run=args.dry_run,
    ):
        record: dict[str, Any] = {args.key: item_id, "ok": not rctx.failed}
        if rctx.failed and rctx.failure_state:
            record["error"] = str(rctx.failure_state.exception)
        else:
            record["steps"] = {
                name: _serialise(sr.value)
                for name, sr in rctx.steps.items()
            }
        output_lines.append(json.dumps(record, default=str))

    out_str = "\n".join(output_lines)
    if args.output:
        Path(args.output).write_text(out_str + "\n", encoding="utf-8")
        summary_ok = sum(1 for ln in output_lines if '"ok": true' in ln)
        summary_fail = len(output_lines) - summary_ok
        print(f"Batch complete: {summary_ok} succeeded, {summary_fail} failed → {args.output}")
    else:
        print(out_str)


def _serialise(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _serialise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialise(v) for v in value]
    return value


# ── validate ───────────────────────────────────────────────────────────────────

def _cmd_validate(args: Any) -> None:
    from .errors import PipelineLoadError
    from .runner import PipelineRunner

    try:
        PipelineRunner(args.pipeline)
        print(f"✓ {args.pipeline} is valid")
    except PipelineLoadError as e:
        print(f"Validation error:\n{e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


# ── schema ─────────────────────────────────────────────────────────────────────

def _cmd_schema(args: Any) -> None:
    doc = _pipeline_jsonschema()
    print(json.dumps(doc, indent=args.indent))


# ── visualise ─────────────────────────────────────────────────────────────────

def _cmd_visualise(args: Any) -> None:
    from .graph import generate_mermaid

    diagram = generate_mermaid(args.pipeline)
    md = f"# Pipeline DAG\n\n```mermaid\n{diagram}```\n"

    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"Diagram written to {args.output}")
    else:
        print(md)


# ── JSONSchema for pipeline YAML ──────────────────────────────────────────────

def _pipeline_jsonschema() -> dict[str, Any]:
    """Generate a JSONSchema document for the pipeline YAML format."""
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "pyconveyor pipeline",
        "description": "pyconveyor pipeline YAML schema",
        "type": "object",
        "properties": {
            "models": {
                "type": "object",
                "description": "Named model configurations",
                "additionalProperties": {
                    "$ref": "#/definitions/ModelConfig"
                },
            },
            "parsers": {
                "type": "object",
                "description": "Named parser callables (module:function)",
                "additionalProperties": {"type": "string"},
            },
            "vocabularies": {
                "type": "object",
                "description": "Named vocabulary definitions",
                "additionalProperties": {
                    "$ref": "#/definitions/VocabularyConfig"
                },
            },
            "steps": {
                "type": "array",
                "items": {"$ref": "#/definitions/Step"},
            },
        },
        "required": ["steps"],
        "definitions": {
            "ModelConfig": {
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "enum": ["openai_compat", "anthropic", "mock"],
                        "default": "openai_compat",
                    },
                    "base_url": {"type": "string"},
                    "api_key": {"type": "string"},
                    "model": {"type": "string"},
                    "timeout": {"type": "integer", "default": 120},
                    "required": {"type": "boolean", "default": True},
                    "temperature": {"type": "number"},
                    "top_p": {"type": "number"},
                    "max_tokens": {"type": "integer"},
                    "seed": {"type": "integer"},
                    "max_retries": {"type": "integer", "default": 2},
                    "retry_delay": {"type": "number", "default": 1.0},
                    "extra_params": {"type": "object"},
                    "pricing": {
                        "type": "object",
                        "properties": {
                            "input_per_1k": {"type": "number"},
                            "output_per_1k": {"type": "number"},
                        },
                    },
                    "cache": {
                        "type": "object",
                        "properties": {
                            "enabled": {"type": "boolean", "default": False},
                            "dir": {"type": "string", "default": ".pyconveyor-cache"},
                            "ttl_days": {"type": "number"},
                        },
                    },
                },
            },
            "VocabularyConfig": {
                "type": "object",
                "properties": {
                    "known": {"type": "array", "items": {"type": "string"}},
                    "fuzzy_match": {"type": "boolean", "default": True},
                    "case_sensitive": {"type": "boolean", "default": False},
                    "file": {"type": "string"},
                },
            },
            "Step": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["llm", "transform", "io", "validate", "parallel", "condition"],
                        "default": "llm",
                    },
                    "model": {"type": "string"},
                    "prompt": {"type": "string"},
                    "system": {"type": "string"},
                    "schema": {"type": "string"},
                    "parser": {"type": "string"},
                    "vars": {"type": "object"},
                    "inputs": {"type": "object"},
                    "fn": {"type": "string"},
                    "if": {"type": "string"},
                    "then": {},
                    "else": {},
                    "steps": {"type": "array"},
                    "max_attempts": {"type": "integer"},
                    "error_feedback": {"type": "boolean"},
                    "retry_hint": {"type": "string"},
                    "retry_on": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["schema", "parse", "timeout", "http_error", "rate_limit"],
                        },
                    },
                    "schema_strict": {"type": "boolean", "default": True},
                    "max_feedback_tokens": {"type": "integer", "default": 4000},
                    "error_template": {"type": "string"},
                    "on_error": {
                        "type": "string",
                        "enum": ["raise", "continue", "skip_remaining"],
                        "default": "raise",
                    },
                    "on_failure": {"type": "string"},
                    "required": {"type": "boolean", "default": True},
                    "condition": {"type": "string"},
                    "temperature": {"type": "number"},
                    "top_p": {"type": "number"},
                    "max_tokens": {"type": "integer"},
                    "seed": {"type": "integer"},
                    "max_prompt_tokens": {"type": "integer"},
                },
            },
        },
    }


# ── Templates for pyconveyor init ─────────────────────────────────────────────

_PIPELINE_TMPL = """\
# pipeline.yaml — generated by pyconveyor init
#
# Edit this file to define your extraction pipeline.
# See: https://pyconveyor.readthedocs.io/en/latest/schema/

models:
  default:
    provider: openai_compat
    base_url: ${OPENAI_BASE_URL}
    api_key:  ${OPENAI_API_KEY}
    model:    ${MODEL_NAME:-gpt-4o-mini}
    timeout:  120

steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema: schemas:ExtractionResult
    max_attempts: 3
"""

_PROMPT_TMPL = """\
{# prompts/extract.j2 #}
Extract structured information from the following document.

Document:
{{ ctx.document }}

Return a JSON object with the following fields:
- "title": string — the document title or a short summary
- "key_points": array of strings — up to 5 key points
"""

_SCHEMAS_TMPL = """\
# schemas.py — Pydantic schemas for your extraction pipeline
from pydantic import BaseModel
from typing import List


class ExtractionResult(BaseModel):
    title: str
    key_points: List[str]
"""

_STEPS_TMPL = """\
# steps.py — custom step functions for your pipeline
# Functions here can be referenced in pipeline.yaml as:
#   fn: steps:my_function
#
# Example:
#   def save_result(result, doc_id):
#       print(f"Saving result for {doc_id}: {result}")
"""

_VSCODE_SETTINGS_TMPL = """\
{{
  "yaml.schemas": {{
    "./{schema_file}": "pipeline.yaml"
  }}
}}
"""
