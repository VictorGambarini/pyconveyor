"""BatchRunner — run a list of items through a pipeline with configurable concurrency."""
from __future__ import annotations

import logging
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .runner import PipelineRunner, RunContext

logger = logging.getLogger("pyconveyor.batch")


class BatchRunner:
    """Process a list of items through a pipeline concurrently.

    Example::

        batch = BatchRunner("pipeline.yaml", max_workers=4)
        for item_id, rctx in batch.run(items, key="doc_id"):
            if rctx.failed:
                print("Failed:", item_id, rctx.failure_state)
            else:
                print("OK:", rctx.steps["extract"].value)

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
        if progress is None:
            try:
                import tqdm  # noqa: F401
                self._progress = True
            except ImportError:
                self._progress = False
        else:
            self._progress = progress

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

        # Build progress wrapper
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
                    # Wrap in a failed RunContext so callers always get a RunContext back
                    rctx = RunContext({})
                    rctx.failed = True
                    from .runner import FailureState
                    rctx.failure_state = FailureState(
                        step_name="<batch>", exception=exc
                    )
                    logger.error("Batch item '%s' raised unexpectedly: %s", item_id, exc)
                yield item_id, rctx

    def run_all(
        self,
        items: list[dict[str, Any]],
        key: str = "id",
        **kwargs: Any,
    ) -> list[tuple[Any, RunContext]]:
        """Like :meth:`run` but collects all results and returns a list."""
        return list(self.run(items, key=key, **kwargs))
