# Concepts

Understanding how pyconveyor pipelines work.

## The three files

Every pyconveyor project has the same shape:

```
your_project/
├── pipeline.yaml      # declares what to do
├── schemas.py         # declares what shape the output must have
└── prompts/
    └── extract.j2     # declares what to ask the model
```

pyconveyor owns the runner. You own the steps, schemas, and prompts.

## Pipeline execution model

When you call `runner.run(input_data)`:

1. The input dict becomes the **context** (`ctx`) — available in every expression and prompt template
2. Steps execute in order, top to bottom
3. Each step's result is stored in `RunContext.steps[name]`
4. Later steps can reference earlier results via expressions like `{{ steps.extract.value }}`
5. The `RunContext` is returned when all steps complete (or a step fails)

```
input_data → ctx
                └─→ step[0] → result → steps["name_0"]
                                └─→ step[1] → result → steps["name_1"]
                                                └─→ step[2] → result → steps["name_2"]
                                                                └─→ RunContext
```

## RunContext

`RunContext` is the object returned by `runner.run()`. It carries:

| Attribute | Type | Description |
|---|---|---|
| `steps` | `dict[str, StepResult]` | Results keyed by step name |
| `metadata` | `dict` | Attempt logs and internal bookkeeping |
| `failed` | `bool` | Whether any required step failed |
| `failure_state` | `FailureState \| None` | Details of the first failure |

```python
result = runner.run(input_data)

result.failed                          # bool
result.failure_state.step_name         # "extract"
result.failure_state.exception         # the exception that caused failure

result.steps["extract"].value          # the validated Pydantic model instance
result.steps["extract"].status         # "success" | "failed" | "skipped"
result.steps["extract"].last_attempt   # most recent AttemptLog
```

## StepResult

Each step produces a `StepResult`:

| Attribute | Description |
|---|---|
| `value` | The step's output (model instance, dict, or `None`) |
| `status` | `"success"`, `"failed"`, or `"skipped"` |
| `last_attempt` | `AttemptLog` — the final attempt's details |
| `attempts` | `list[AttemptLog]` — full attempt history |

`last_attempt` is populated even on successful steps, useful for observability:

```python
step = result.steps["extract"]
print(step.last_attempt.elapsed_seconds)   # how long the final attempt took
print(step.last_attempt.attempt_number)    # which attempt succeeded (1-indexed)
```

## Context expressions

Step inputs and conditions use `{{ expr }}` syntax. Expressions are evaluated against a context that exposes:

- `ctx` — the input dict passed to `runner.run()`
- `steps` — a dict of completed step results (by name)
- Helper functions: `first_non_none`, `active_models`, `len`

```yaml
steps:
  - name: summarise
    type: transform
    fn: steps:summarise
    inputs:
      text:    "{{ ctx.document }}"
      primary: "{{ steps.extract.value }}"
```

Expressions are **AST-whitelisted** — only a safe subset of Python is allowed. See [Expression Language](guides/expressions.md) for the full whitelist and security model.

## The determinism philosophy

pyconveyor is built around a single constraint: given the same input and the same model (with `temperature: 0`, `seed: 42`), runs should produce the same output.

This has consequences:

- **No hidden state.** Every dependency between steps is explicit in YAML.
- **Side effects are explicit.** Your `io` steps handle database writes and other side effects. The optional `outputs:` block writes step results to disk after the run completes — declared in YAML so the intent is always visible.
- **No async.** Parallel steps use `ThreadPoolExecutor`. The execution model is synchronous and predictable.
- **Schema validation is strict by default.** If a model returns output that doesn't match the schema, it retries — it doesn't silently accept bad data.

## Load-time vs run-time

pyconveyor validates everything it can at **load time** — before any API call:

- All `fn:` and `schema:` references resolve to importable Python callables
- All `model:` references exist in the `models:` block
- All `{{ expr }}` expressions pass the AST whitelist
- Required fields are present on every step
- No duplicate step names

If any check fails, `PipelineRunner("pipeline.yaml")` raises `PipelineLoadError` with the YAML file name, line number, and a plain-English description of the problem.

Run-time failures (model timeouts, schema validation errors, Python exceptions in step functions) are handled by the retry and `on_error` mechanisms described in [Step Types](guides/step-types.md).
