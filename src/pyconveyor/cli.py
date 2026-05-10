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
    p_init.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Guided setup: define fields and provider interactively",
    )

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

    # schema (sub-group: emit | infer)
    p_schema = sub.add_parser("schema", help="JSONSchema utilities")
    schema_sub = p_schema.add_subparsers(dest="schema_command")
    # schema emit (existing behaviour; also the default when no sub-command given)
    p_schema_emit = schema_sub.add_parser("emit", help="Emit JSONSchema for the pipeline YAML format")
    p_schema_emit.add_argument("--indent", type=int, default=2)
    # schema infer
    p_schema_infer = schema_sub.add_parser("infer", help="Infer a schemas.py from sample JSON output")
    p_schema_infer.add_argument("pipeline", help="Path to pipeline.yaml")
    p_schema_infer.add_argument("--sample", required=True, help="Path to a .json or .jsonl sample file")
    p_schema_infer.add_argument("--step", default=None, help="Step name to infer schema for (default: first llm step)")
    p_schema_infer.add_argument("--output", "-o", default=None, help="Output file path (default: stdout)")
    # keep --indent on the parent for the alias `pyconveyor schema` → emit
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

    # benchmark
    p_bench = sub.add_parser(
        "benchmark",
        help="Run benchmark cases against one or more pipelines and generate a report",
    )
    p_bench.add_argument("benchmark_dir", help="Directory containing benchmark cases")
    p_bench.add_argument(
        "--pipeline", "-p",
        dest="pipelines",
        metavar="PIPELINE",
        action="append",
        required=True,
        help="Pipeline YAML file to benchmark (repeat for multiple)",
    )
    p_bench.add_argument(
        "--report", "-r",
        default="benchmark_report.html",
        help="Output HTML report path (default: benchmark_report.html)",
    )
    p_bench.add_argument(
        "--pdf",
        action="store_true",
        help="Also write a PDF alongside the HTML report (requires WeasyPrint)",
    )
    p_bench.add_argument(
        "--sections",
        default=None,
        help=(
            "Comma-separated list of sections to include. "
            "Available: overall_summary, per_step_accuracy, pipeline_comparison, "
            "mermaid_graph, plots, per_case_breakdown, attempt_logs. "
            "Default: all except attempt_logs."
        ),
    )
    p_bench.add_argument(
        "--pass-threshold",
        type=float,
        default=1.0,
        help="Minimum score to count a case as passed (default: 1.0)",
    )
    p_bench.add_argument(
        "--title",
        default="Pipeline Benchmark Report",
        help="Report title",
    )

    # vocab
    p_vocab = sub.add_parser("vocab", help="Vocabulary management commands")
    vocab_sub = p_vocab.add_subparsers(dest="vocab_command", required=True)
    p_vocab_review = vocab_sub.add_parser(
        "review", help="Review pending vocabulary suggestions"
    )
    p_vocab_review.add_argument("pipeline", help="Path to pipeline.yaml")
    p_vocab_review.add_argument(
        "--auto-accept", action="store_true",
        help="Accept all pending suggestions without prompting"
    )

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
        if getattr(args, "schema_command", None) == "infer":
            _cmd_schema_infer(args)
        else:
            # Both "emit" sub-command and bare "pyconveyor schema" go here
            _cmd_schema(args)
    elif args.command in ("visualise", "visualize"):
        _cmd_visualise(args)
    elif args.command == "benchmark":
        _cmd_benchmark(args)
    elif args.command == "vocab":
        if args.vocab_command == "review":
            _cmd_vocab_review(args)


# ── init ───────────────────────────────────────────────────────────────────────

def _cmd_init(args: Any) -> None:
    if getattr(args, "interactive", False):
        _cmd_init_interactive(Path(args.directory))
    else:
        _cmd_init_static(args)


def _cmd_init_static(args: Any) -> None:
    target = Path(args.directory)
    target.mkdir(parents=True, exist_ok=True)

    _write_template(target / "pipeline.yaml", _PIPELINE_TMPL)
    _write_template(target / "prompts" / "extract.j2", _PROMPT_TMPL)
    _write_template(target / "schemas.py", _SCHEMAS_TMPL)
    _write_template(target / "steps.py", _STEPS_TMPL)
    (target / "vocabularies").mkdir(exist_ok=True)

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


def _cmd_init_interactive(target: Path) -> None:
    from .schema_builder import yaml_dict_to_model

    print()
    subject = input('What are you extracting from? (e.g. "articles", "invoices") ').strip() or "documents"

    print()
    print("Define your output fields. Format: name:type")
    print("Types: str, int, float, bool, list[str], list[int], list[float], dict[str,str]")
    print("Append  | None  to make a field optional  (e.g.  score:int | None)")
    print("Press Enter on an empty line when done.")
    print()

    fields: dict[str, str] = {}
    while True:
        line = input("> ").strip()
        if not line:
            break
        if ":" not in line:
            print("  Format must be  name:type  — try again.")
            continue
        fname, ftype = line.split(":", 1)
        fname = fname.strip()
        ftype = ftype.strip()
        if not fname.isidentifier():
            print(f"  '{fname}' is not a valid Python identifier — try again.")
            continue
        try:
            yaml_dict_to_model("_Tmp", {fname: ftype})
        except Exception:
            print(
                f"  Unsupported type '{ftype}'. "
                "Supported: str, int, float, bool, list[str], list[int], list[float], dict[str,str]  (append | None for optional)"
            )
            continue
        fields[fname] = ftype

    if not fields:
        print("No fields defined — using default schema.")
        fields = {"title": "str", "key_points": "list[str]"}

    print()
    print("Which LLM provider?")
    print("  1) OpenAI (or compatible)")
    print("  2) Anthropic Claude")
    print("  3) Ollama (local)")
    choice = input("Enter choice [1]: ").strip() or "1"

    provider_config = _provider_config_for_choice(choice)

    schema_lines = "\n".join(f"      {k}: {v}" for k, v in fields.items())

    pipeline_src = _PIPELINE_INTERACTIVE_TMPL.format(
        provider_block=provider_config,
        schema_block=schema_lines,
    )

    target.mkdir(parents=True, exist_ok=True)
    _write_template(target / "pipeline.yaml", pipeline_src)
    _write_template(target / "prompts" / "extract.j2", _PROMPT_TMPL)
    _write_template(target / "steps.py", _STEPS_TMPL)

    schema_path = target / "pyconveyor-schema.json"
    schema_doc = _pipeline_jsonschema()
    schema_path.write_text(json.dumps(schema_doc, indent=2) + "\n", encoding="utf-8")
    _write_template(
        target / ".vscode" / "settings.json",
        _VSCODE_SETTINGS_TMPL.format(schema_file="pyconveyor-schema.json"),
    )

    print(f"\nBootstrapped {target}/ — 5 files written.\n")
    print(f"  pipeline.yaml          — inline schema for '{subject}'")
    print("  prompts/extract.j2     — prompt with {{ schema_hint }} pre-filled")
    print("  steps.py               — custom step functions")
    print("  pyconveyor-schema.json — JSONSchema for editor autocomplete")
    print("  .vscode/settings.json  — editor autocomplete config")
    _print_run_instructions(target, provider_config)



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

    reserved_keys = {"ok", "error", "steps"}
    if args.key in reserved_keys:
        print(
            f"Error: --key '{args.key}' conflicts with reserved output fields"
            f" ({', '.join(sorted(reserved_keys))}). Choose a different key.",
            file=sys.stderr,
        )
        sys.exit(1)

    runner = BatchRunner(
        args.pipeline,
        max_workers=args.workers,
        progress=not args.no_progress,
    )

    output_lines: list[str] = []
    ok_count = 0
    for item_id, rctx in runner.run(
        items,
        key=args.key,
        use_cache=not args.no_cache,
        dry_run=args.dry_run,
    ):
        record: dict[str, Any] = {}
        record[args.key] = item_id
        record["ok"] = not rctx.failed
        if rctx.failed and rctx.failure_state:
            record["error"] = str(rctx.failure_state.exception)
        else:
            ok_count += 1
            record["steps"] = {
                name: _serialise(sr.value)
                for name, sr in rctx.steps.items()
            }
        output_lines.append(json.dumps(record, default=str))

    out_str = "\n".join(output_lines)
    if args.output:
        Path(args.output).write_text(out_str + "\n", encoding="utf-8")
        summary_fail = len(output_lines) - ok_count
        print(f"Batch complete: {ok_count} succeeded, {summary_fail} failed → {args.output}")
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


def _cmd_schema_infer(args: Any) -> None:
    from .infer import infer_schema_source
    from .runner import _inline_schema_name

    sample_path = Path(args.sample)
    if not sample_path.exists():
        print(f"Error: sample file not found: {sample_path}", file=sys.stderr)
        sys.exit(1)

    raw = sample_path.read_text(encoding="utf-8").strip()

    if sample_path.suffix == ".jsonl" or (raw and raw[0] != "{" and "\n" in raw):
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if not lines:
            print("Error: sample file is empty.", file=sys.stderr)
            sys.exit(1)
        if len(lines) > 1:
            print(
                f"Warning: {sample_path} has {len(lines)} records. "
                "Using the first record only.",
                file=sys.stderr,
            )
        sample = json.loads(lines[0])
    else:
        sample = json.loads(raw)

    if not isinstance(sample, dict):
        print("Error: sample must be a JSON object (dict), not a list or scalar.", file=sys.stderr)
        sys.exit(1)

    pipeline_path = Path(args.pipeline)
    step_name = args.step or _first_llm_step_name(pipeline_path)
    class_name = _inline_schema_name(step_name)

    source = infer_schema_source(class_name, sample)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(source, encoding="utf-8")
        print(f"Wrote {out_path}")
    else:
        print(source)


def _first_llm_step_name(pipeline_path: Path) -> str:
    """Return the name of the first llm step in the pipeline, or 'Extract'."""
    import yaml as _yaml

    try:
        spec = _yaml.safe_load(pipeline_path.read_text(encoding="utf-8")) or {}
        for step in spec.get("steps", []):
            if step.get("type", "llm") == "llm":
                return str(step.get("name", "Extract"))
    except Exception:
        pass
    return "Extract"


def _provider_config_for_choice(choice: str) -> str:
    return {
        "1": _PROVIDER_OPENAI,
        "2": _PROVIDER_ANTHROPIC,
        "3": _PROVIDER_OLLAMA,
    }.get(choice, _PROVIDER_OPENAI)


def _print_run_instructions(target: Path, provider_block: str) -> None:
    if "ANTHROPIC" in provider_block:
        key_hint = "export ANTHROPIC_API_KEY=sk-ant-..."
    elif "ollama" in provider_block:
        key_hint = "# Ollama: ensure 'ollama serve' is running"
    else:
        key_hint = "export OPENAI_API_KEY=sk-..."
    print(f"\nRun:\n  cd {target}/\n  {key_hint}")
    print('  pyconveyor run pipeline.yaml --input \'{"document": "..."}\'')


# ── benchmark ─────────────────────────────────────────────────────────────────

def _cmd_benchmark(args: Any) -> None:
    from .benchmark import BenchmarkRunner
    from .report import generate_report

    benchmark_dir = Path(args.benchmark_dir)
    if not benchmark_dir.exists():
        print(f"Error: benchmark directory not found: {benchmark_dir}", file=sys.stderr)
        sys.exit(1)

    sections: list[str] | None = None
    if args.sections:
        sections = [s.strip() for s in args.sections.split(",") if s.strip()]

    runner = BenchmarkRunner(
        benchmark_dir=benchmark_dir,
        pipelines=args.pipelines,
        pass_threshold=args.pass_threshold,
    )
    summary = runner.run()

    # Print a quick console summary
    print(f"\nBenchmark complete — {len(summary.case_names)} cases")
    for pr in summary.pipelines:
        label = Path(pr.pipeline_path).name
        ok = sum(1 for c in pr.cases if c.status == "ok")
        err = sum(1 for c in pr.cases if c.status == "error")
        print(
            f"  {label}: mean={pr.overall_mean_accuracy:.0%}  "
            f"pass={pr.overall_pass_rate:.0%}  "
            f"errors={err}/{ok + err}"
        )

    generate_report(
        summary,
        output=args.report,
        sections=sections,
        title=args.title,
        pdf=args.pdf,
    )
    print(f"\nReport written to: {args.report}")
    if args.pdf:
        pdf_path = Path(args.report).with_suffix(".pdf")
        print(f"PDF written to:    {pdf_path}")


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


# ── vocab review ──────────────────────────────────────────────────────────────

def _cmd_vocab_review(args: Any) -> None:
    """Interactive review of pending vocabulary suggestions."""
    import yaml

    from .vocab import Vocabulary

    pipeline_path = Path(args.pipeline).resolve()
    pipeline_dir = pipeline_path.parent

    try:
        with pipeline_path.open(encoding="utf-8") as f:
            spec = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error reading pipeline: {e}", file=sys.stderr)
        sys.exit(1)

    vocab_block = spec.get("vocabularies", {})
    if not vocab_block:
        print("No vocabularies declared in this pipeline.")
        return

    # Load all vocab files
    vocabs: dict[str, tuple[Vocabulary, Path]] = {}
    for label, value in vocab_block.items():
        if isinstance(value, str):
            vocab_path = pipeline_dir / value
            if not vocab_path.exists():
                print(f"  Vocab file not found: {vocab_path} — skipping", file=sys.stderr)
                continue
            vocab = Vocabulary.from_file(vocab_path)
            vocabs[label] = (vocab, vocab_path)
        elif isinstance(value, dict):
            persist = value.get("persist")
            if persist and isinstance(persist, str):
                vocab_path = pipeline_dir / persist
            elif persist is True:
                vocab_path = pipeline_dir / "vocabularies" / f"{label}.yaml"
            else:
                print(f"  Vocab '{label}' has no persist path — skipping")
                continue
            if not vocab_path.exists():
                print(f"  No pending suggestions file for '{label}' — skipping")
                continue
            vocab = Vocabulary.from_file(vocab_path)
            vocabs[label] = (vocab, vocab_path)

    if not vocabs:
        print("No vocabulary files found to review.")
        return

    any_pending = False
    for label, (vocab, vocab_path) in vocabs.items():
        if not vocab.pending:
            continue
        any_pending = True

        print(f"\nVocabulary: {vocab.label}")
        if vocab.description:
            print(f"Description: {vocab.description}")
        print(f"Known terms: {', '.join(sorted(vocab.known))}")
        if vocab.denied:
            print(f"Denied terms: {', '.join(sorted(vocab.denied))}")
        print(f"\nPending suggestions ({len(vocab.pending)}):")
        for i, entry in enumerate(vocab.pending, 1):
            raw = entry.get("raw_value", "?")
            seen = entry.get("seen", 1)
            match_type = entry.get("match_type", "novel")
            ideal = entry.get("ideal_value")
            ideal_str = f" (ideal: '{ideal}')" if ideal else ""
            matched = entry.get("matched_to")
            matched_str = f" → fuzzy match for '{matched}'" if matched else ""
            print(f"  {i}. '{raw}'{ideal_str} — {match_type}{matched_str} (seen {seen}×)")

        if args.auto_accept:
            for entry in vocab.pending:
                vocab.add_term(entry["raw_value"])
            print(f"\n→ Auto-accepted all {len(vocab.pending)} terms into '{label}'.")
            vocab.pending.clear()
            vocab.save(vocab_path)
            continue

        print("\nEnter numbers to accept (comma-separated), 'd<numbers>' to deny, or Enter to skip.")
        print("Example: '1,3' to accept; 'd2' to deny #2; '1,3 d2' for both.")
        try:
            response = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return

        if not response:
            continue

        accept_indices: set[int] = set()
        deny_indices: set[int] = set()

        for token in response.replace(",", " ").split():
            if token.startswith("d") or token.startswith("D"):
                nums = token[1:].split(",") if "," in token[1:] else [token[1:]]
                for n in nums:
                    try:
                        deny_indices.add(int(n.strip()) - 1)
                    except ValueError:
                        pass
            else:
                try:
                    accept_indices.add(int(token.strip()) - 1)
                except ValueError:
                    pass

        kept_pending: list[dict[str, Any]] = []
        for i, entry in enumerate(vocab.pending):
            raw = entry["raw_value"]
            if i in accept_indices:
                vocab.add_term(raw)
                print(f"  ✓ Added '{raw}' to {label}")
            elif i in deny_indices:
                vocab.denied.add(raw)
                print(f"  ✗ Denied '{raw}' in {label}")
            else:
                kept_pending.append(entry)

        vocab.pending = kept_pending
        vocab.save(vocab_path)
        print(f"  Saved {vocab_path}")

    if not any_pending:
        print("No pending suggestions found across all vocabularies.")


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
                    "schema": {
                        "oneOf": [
                            {"type": "string", "description": "module:ClassName reference"},
                            {
                                "type": "object",
                                "description": "Inline field map. Values: str, int, float, bool, list[T], dict[str,T], T|None",
                                "additionalProperties": {"type": "string"},
                            },
                        ]
                    },
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
{# schema_hint is auto-generated from your schema — edit or remove as needed #}
Extract structured information from the following document.

{{ schema_hint }}

Document:
{{ ctx.document }}
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

_PIPELINE_INTERACTIVE_TMPL = """\
# pipeline.yaml — generated by pyconveyor init --interactive

models:
  default:
{provider_block}

steps:
  - name: extract
    type: llm
    model: default
    prompt: prompts/extract.j2
    schema:
{schema_block}
    max_attempts: 3
"""

# Provider config blocks (indented 4 spaces for the models.default: key)
_PROVIDER_OPENAI = """\
    provider: openai_compat
    api_key:  ${OPENAI_API_KEY}
    model:    ${MODEL_NAME:-gpt-4o-mini}
    timeout:  120"""

_PROVIDER_ANTHROPIC = """\
    provider: anthropic
    api_key:  ${ANTHROPIC_API_KEY}
    model:    ${MODEL_NAME:-claude-haiku-4-5-20251001}
    timeout:  120"""

_PROVIDER_OLLAMA = """\
    provider: openai_compat
    base_url: ${OPENAI_BASE_URL:-http://localhost:11434/v1}
    api_key:  ollama
    model:    ${MODEL_NAME:-llama3.2}
    timeout:  120"""
