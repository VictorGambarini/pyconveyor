"""BatchRunner — run a list of items through a pipeline with configurable concurrency."""
from __future__ import annotations

import logging
from collections.abc import Callable, Generator, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .runner import FailureState, PipelineRunner, RunContext

logger = logging.getLogger("pyconveyor.batch")


# ── BatchResult ────────────────────────────────────────────────────────────────

@dataclass
class BatchSummary:
    """Aggregate statistics for a completed batch run."""

    total: int
    succeeded: int
    failed: int
    error_rate: float
    failed_ids: list[Any] = field(default_factory=list)


class BatchResult:
    """Collected results from :meth:`BatchRunner.run_all`.

    Supports iteration so existing ``for item_id, rctx in result`` code works
    unchanged.

    Example::

        result = batch.run_all(items)
        print(result.summary())
        for item_id, rctx in result.failures:
            print("Failed:", item_id, rctx.failure_state)
    """

    def __init__(self, items: list[tuple[Any, RunContext]]) -> None:
        self._items = items

    def __iter__(self) -> Iterator[tuple[Any, RunContext]]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int) -> tuple[Any, RunContext]:
        return self._items[index]

    @property
    def successes(self) -> list[tuple[Any, RunContext]]:
        """Items that completed without failure."""
        return [(k, v) for k, v in self._items if not v.failed]

    @property
    def failures(self) -> list[tuple[Any, RunContext]]:
        """Items that failed (pipeline error or uncaught exception)."""
        return [(k, v) for k, v in self._items if v.failed]

    @property
    def error_rate(self) -> float:
        """Fraction of items that failed (0.0–1.0)."""
        if not self._items:
            return 0.0
        return len(self.failures) / len(self._items)

    def summary(self) -> BatchSummary:
        """Return aggregate statistics for this batch."""
        total = len(self._items)
        failed_pairs = self.failures
        succeeded = total - len(failed_pairs)
        return BatchSummary(
            total=total,
            succeeded=succeeded,
            failed=len(failed_pairs),
            error_rate=self.error_rate,
            failed_ids=[k for k, _ in failed_pairs],
        )


# ── BatchRunner ────────────────────────────────────────────────────────────────

class BatchRunner:
    """Process a list of items through a pipeline concurrently.

    Example::

        batch = BatchRunner("pipeline.yaml", max_workers=4)
        result = batch.run_all(items, key="doc_id")
        print(result.summary())
        for item_id, rctx in result.failures:
            print("Failed:", item_id, rctx.failure_state)

    Args:
        pipeline_path: Path to the pipeline YAML file.
        max_workers: Maximum number of parallel threads (default: 4).
        progress: Show a tqdm progress bar.  Defaults to True if tqdm is
            installed, False otherwise.
    """

    def __init__(
        self,
        pipeline_path: str | Path,
        max_workers: int = 4,
        progress: bool | None = None,
    ) -> None:
        self._runner = PipelineRunner(pipeline_path)
        self._max_workers = max_workers
        self._item_hooks: list[Callable[..., Any]] = []
        if progress is None:
            try:
                import tqdm  # noqa: F401
                self._progress = True
            except ImportError:
                self._progress = False
        else:
            self._progress = progress

    # ── Hooks ──────────────────────────────────────────────────────────────────

    def on_batch_item_end(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a callback called after each batch item completes.

        Signature: ``fn(item_id: Any, rctx: RunContext) -> None``

        Useful for streaming results to a database or file as each item finishes
        rather than waiting for the whole batch.
        """
        self._item_hooks.append(fn)
        return fn

    # ── Run API ────────────────────────────────────────────────────────────────

    def run(
        self,
        items: list[dict[str, Any]],
        key: str = "id",
        model_overrides: dict[str, dict[str, Any]] | None = None,
        use_cache: bool = True,
        refresh_cache: bool = False,
        dry_run: bool = False,
    ) -> Generator[tuple[Any, RunContext], None, None]:
        """Run each item through the pipeline, yielding ``(item_id, RunContext)`` as they complete.

        Args:
            items: List of input dicts.  Each must have *key* field.
            key: Field name used as the item identifier in yielded tuples.
            model_overrides: Per-model parameter overrides forwarded to each run.
            use_cache: Whether to check the response cache.
            refresh_cache: Ignore cached responses; overwrite on success.
            dry_run: Skip LLM/fn calls.

        Yields:
            ``(item_id, rctx)`` tuples in completion order (not submission order).
        """
        if not items:
            return

        iterable: Any = items
        if self._progress:
            try:
                from tqdm import tqdm

                iterable = tqdm(items, desc="pyconveyor batch", unit="item")
            except ImportError:
                pass

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            future_to_id: dict[Any, Any] = {}
            for item in iterable:
                item_id = item.get(key, id(item))
                fut = pool.submit(
                    self._runner.run,
                    item,
                    model_overrides,
                    use_cache,
                    refresh_cache,
                    dry_run,
                )
                future_to_id[fut] = item_id

            for fut in as_completed(future_to_id):
                item_id = future_to_id[fut]
                try:
                    rctx: RunContext = fut.result()
                except Exception as exc:
                    rctx = RunContext({})
                    rctx.failed = True
                    rctx.failure_state = FailureState(
                        step_name="<batch>", exception=exc
                    )
                    logger.error("Batch item '%s' raised unexpectedly: %s", item_id, exc)

                for hook in self._item_hooks:
                    try:
                        hook(item_id, rctx)
                    except Exception as he:
                        logger.warning("on_batch_item_end hook error: %s", he)

                yield item_id, rctx

    def run_all(
        self,
        items: list[dict[str, Any]],
        key: str = "id",
        **kwargs: Any,
    ) -> BatchResult:
        """Like :meth:`run` but collects all results into a :class:`BatchResult`."""
        return BatchResult(list(self.run(items, key=key, **kwargs)))
