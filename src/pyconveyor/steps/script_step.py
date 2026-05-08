"""transform / io / validate step execution."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..runner import RunContext

logger = logging.getLogger("pyconveyor.runner")


def execute_script_step(
    step: dict[str, Any],
    resolved_inputs: dict[str, Any],
    fn: Callable[..., Any],
    rctx: "RunContext",
    dry_run: bool = False,
) -> Any:
    """Execute a transform / io / validate step.

    Args:
        step: Parsed step spec dict.
        resolved_inputs: Pre-resolved ``inputs:`` values.
        fn: The callable referenced by ``fn:``.
        rctx: Current run context.
        dry_run: Skip the actual function call; return None.

    Returns:
        The function's return value, or None in dry-run mode.

    Raises:
        Any exception raised by *fn* (caller handles on_error).
    """
    name: str = step["name"]
    stype: str = step.get("type", "transform")
    logger.info("Step '%s' (%s): calling %s", name, stype, fn)

    if dry_run:
        logger.debug("Step '%s': dry-run — skipping fn call", name)
        return None

    result = fn(**resolved_inputs)

    if stype == "validate" and not result:
        raise ValueError(
            f"Validate step '{name}' returned falsy — aborting pipeline"
        )

    return result
