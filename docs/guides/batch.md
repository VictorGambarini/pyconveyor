# Batch Processing

`BatchRunner` runs a list of items through a pipeline concurrently using a thread pool.
The companion `pyconveyor batch` CLI subcommand handles the common case of processing
a JSONL file without writing any Python.

---

## Quick start

```python
from pyconveyor import BatchRunner

batch = BatchRunner("pipeline.yaml", max_workers=4)
result = batch.run_all(items, key="doc_id")

print(result.summary())
# BatchSummary(total=100, succeeded=98, failed=2, error_rate=0.02, ...)

for item_id, rctx in result.failures:
    print(f"Failed: {item_id} — {rctx.failure_state.exception}")
```

---

## `BatchRunner`

```python
BatchRunner(
    pipeline_path,      # str | Path
    max_workers=4,      # int — parallel threads
    progress=None,      # bool | None — auto-detect tqdm
)
```

### `.run(items, key="id", ...)` → generator

Yields `(item_id, RunContext)` tuples in completion order as they finish.
Use this when you want to process results as they arrive instead of waiting for all items.

```python
for item_id, rctx in batch.run(items):
    if not rctx.failed:
        save_to_db(item_id, rctx.steps["extract"].value)
```

### `.run_all(items, key="id", ...)` → `BatchResult`

Collects all results and returns a `BatchResult`.

**Common parameters (both methods):**

| Parameter | Default | Description |
|---|---|---|
| `items` | — | List of input dicts |
| `key` | `"id"` | Field name used as the item identifier |
| `model_overrides` | `None` | Per-model parameter overrides |
| `use_cache` | `True` | Check the response cache |
| `refresh_cache` | `False` | Ignore cached responses |
| `dry_run` | `False` | Skip LLM calls |

---

## `BatchResult`

`BatchResult` is iterable and supports index access, so existing code that does
`for item_id, rctx in batch.run_all(items)` continues to work unchanged.

```python
result = batch.run_all(items)

len(result)               # total items
result[0]                 # (item_id, rctx) at index 0
list(result)              # all (item_id, rctx) pairs

result.successes          # list[(item_id, rctx)] — items that didn't fail
result.failures           # list[(item_id, rctx)] — items that failed
result.error_rate         # float — failures / total (0.0 if empty)
result.summary()          # BatchSummary dataclass
```

### `BatchSummary`

```python
@dataclass
class BatchSummary:
    total: int
    succeeded: int
    failed: int
    error_rate: float       # 0.0–1.0
    failed_ids: list[Any]   # IDs of failed items
```

---

## `on_batch_item_end` hook

Register a callback that fires after each item completes.
Useful for streaming results to a database without buffering the whole batch.

```python
batch = BatchRunner("pipeline.yaml", max_workers=8)

@batch.on_batch_item_end
def stream_to_db(item_id, rctx):
    if not rctx.failed:
        db.insert(item_id, rctx.steps["extract"].value)

batch.run_all(items)
```

Signature: `fn(item_id: Any, rctx: RunContext) -> None`

Hook errors are logged and do not abort the batch.

---

## CLI: `pyconveyor batch`

```bash
pyconveyor batch pipeline.yaml \
  --input documents.jsonl \
  --output results.jsonl \
  --workers 8 \
  --key doc_id
```

**Input format (JSONL):**

```jsonl
{"doc_id": "001", "text": "First document"}
{"doc_id": "002", "text": "Second document"}
```

**Output format (JSONL):**

```jsonl
{"doc_id": "002", "ok": true, "steps": {"extract": {"title": "..."}}}
{"doc_id": "001", "ok": true, "steps": {"extract": {"title": "..."}}}
```

Results arrive in completion order (not input order). If an item fails:

```jsonl
{"doc_id": "003", "ok": false, "error": "Pipeline aborted at step 'extract': ..."}
```

See the [CLI Reference](../reference/cli.md#pyconveyor-batch) for all options.

---

## Progress bar

`BatchRunner` shows a `tqdm` progress bar when the `tqdm` package is installed.
Pass `progress=False` to suppress it, or install tqdm with:

```bash
pip install pyconveyor[progress]
```
