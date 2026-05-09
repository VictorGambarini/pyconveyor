# Hooks

`PipelineRunner` and `BatchRunner` expose hook points that let you observe and react
to pipeline events without modifying the pipeline itself.

---

## `PipelineRunner` hooks

### `on_run_start`

Called once before any steps execute.

```python
runner = PipelineRunner("pipeline.yaml")

@runner.on_run_start
def log_start(input_data: dict) -> None:
    print(f"Starting run with {len(input_data)} input keys")

result = runner.run({"document": "..."})
```

Signature: `fn(input_data: dict) -> None`

### `on_run_end`

Called once after the run completes, whether it succeeded or failed.

```python
@runner.on_run_end
def log_end(rctx: RunContext) -> None:
    summary = rctx.summary()
    print(f"Run complete: {summary.steps_run} steps, {summary.elapsed_seconds:.2f}s")
    if rctx.failed:
        alert(f"Pipeline failed: {rctx.failure_state}")
```

Signature: `fn(rctx: RunContext) -> None`

### `on_step_end`

Called after each step completes (including failed steps).

```python
@runner.on_step_end
def track_step(step_name: str, result, rctx: RunContext) -> None:
    metrics.record(step_name, rctx.steps[step_name].status)
```

Signature: `fn(step_name: str, result: Any, rctx: RunContext) -> None`

### `on_llm_call`

Called after each LLM API call (including retries).

```python
@runner.on_llm_call
def log_llm(step_name: str, model: str, response) -> None:
    print(f"LLM call: step={step_name} model={model}")
```

Signature: `fn(step_name: str, model: str, response: Any) -> None`

---

## `BatchRunner` hooks

### `on_batch_item_end`

Called after each item completes, in the thread that processed it.

```python
batch = BatchRunner("pipeline.yaml", max_workers=4)

@batch.on_batch_item_end
def save(item_id, rctx: RunContext) -> None:
    if not rctx.failed:
        db.save(item_id, rctx.steps["extract"].value)
```

Signature: `fn(item_id: Any, rctx: RunContext) -> None`

!!! warning "Thread safety"
    `on_batch_item_end` may be called concurrently from multiple worker threads.
    Ensure your callback is thread-safe (e.g. use a thread-safe queue or lock
    around shared state).

---

## Behaviour

- Hooks registered with the decorator form (`@runner.on_run_end`) or the method
  form (`runner.on_run_end(fn)`) are equivalent; both return the original function.
- Multiple hooks of the same type are called in registration order.
- Hook errors are caught, logged as warnings, and do not abort the run or batch.
- Hooks run synchronously in the calling thread; long-running hooks block step
  execution.

!!! note "`on_llm_call` and parallel steps"
    `on_llm_call` fires for LLM calls in top-level steps only. LLM calls made
    inside a `type: parallel` branch are not currently surfaced to this hook.
    Use `on_step_end` to observe parallel step results.

---

## Combining hooks

```python
runner = PipelineRunner("pipeline.yaml")

started: dict[str, float] = {}

@runner.on_run_start
def record_start(data):
    started["t"] = time.monotonic()

@runner.on_run_end
def record_end(rctx):
    elapsed = time.monotonic() - started.get("t", 0)
    metrics.histogram("pipeline.duration", elapsed)

@runner.on_step_end
def per_step(name, value, rctx):
    metrics.increment(f"step.{name}.{rctx.steps[name].status}")
```
