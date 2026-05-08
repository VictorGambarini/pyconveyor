"""Parallel step execution using ThreadPoolExecutor."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..runner import PipelineRunner, RunContext

logger = logging.getLogger("pyconveyor.runner")


def execute_parallel_step(
    step: dict[str, Any],
    rctx: "RunContext",
    execute_single: Callable[..., Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute child steps concurrently.

    Args:
        step: Parallel step spec with ``steps:`` list.
        rctx: Current run context (shared read-only; results written under lock).
        execute_single: Callback ``execute_single(child_step, rctx, **kwargs)``
            that returns the child step result.

    Returns:
        Dict mapping child step name → result.
    """
    children: list[dict[str, Any]] = step.get("steps", [])
    results: dict[str, Any] = {}
    errors: dict[str, Exception] = {}

    with ThreadPoolExecutor(max_workers=len(children) or 1) as pool:
        future_to_name = {
            pool.submit(execute_single, child, rctx, **kwargs): child["name"]
            for child in children
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                child_spec = next(c for c in children if c["name"] == name)
                required: bool = child_spec.get("required", True)
                if required:
                    errors[name] = exc
                    logger.warning(
                        "Required parallel child '%s' failed: %s", name, exc
                    )
                else:
                    results[name] = None
                    logger.info(
                        "Optional parallel child '%s' failed (continuing): %s", name, exc
                    )

    if errors:
        # Re-raise the first error from a required child
        first_name, first_exc = next(iter(errors.items()))
        raise RuntimeError(
            f"Parallel step '{step['name']}': required child '{first_name}' failed"
        ) from first_exc

    return results
