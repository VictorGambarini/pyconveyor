"""Condition step execution."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runner import RunContext

logger = logging.getLogger("pyconveyor.runner")


def execute_condition_step(
    step: dict[str, Any],
    rctx: RunContext,
    eval_expr: Callable[[str], Any],
    execute_branch: Callable[[list[dict[str, Any]], RunContext], Any],
) -> Any:
    """Evaluate ``if:`` and run the matching branch.

    Args:
        step: Condition step spec with ``if:``, ``then:``, and optional ``else:``.
        rctx: Current run context.
        eval_expr: Callable to evaluate an expression string.
        execute_branch: Callable to execute a list of step specs.

    Returns:
        Result of the branch that was executed, or None if ``else:`` branch is
        absent and condition is False.
    """
    condition_expr: str = step.get("if", "False")
    condition_value = eval_expr(condition_expr)

    logger.info(
        "Step '%s' (condition): '%s' → %s",
        step["name"],
        condition_expr,
        bool(condition_value),
    )

    branch_key = "then" if condition_value else "else"
    branch = step.get(branch_key)

    if branch is None:
        logger.debug("Step '%s': no '%s' branch, skipping", step["name"], branch_key)
        return None

    if isinstance(branch, dict):
        branch_steps = [branch]
    elif isinstance(branch, list):
        branch_steps = branch
    else:
        # String name reference — not yet supported; log and skip
        logger.warning(
            "Step '%s': branch reference '%s' is a step name string — "
            "step-name references in condition branches are not yet supported; skipping",
            step["name"],
            branch,
        )
        return None

    return execute_branch(branch_steps, rctx)
