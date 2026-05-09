"""Jinja2 prompt rendering."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateSyntaxError,
    UndefinedError,
)

from .errors import PyConveyorError


class PromptRenderError(PyConveyorError):
    """Raised when a Jinja2 template cannot be rendered."""


def _make_env(template_dir: str | Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_prompt(
    template_dir: str | Path,
    template_name: str,
    **kwargs: Any,
) -> str:
    """Render a Jinja2 prompt template from a file.

    Args:
        template_dir: Directory containing templates.
        template_name: Template filename relative to *template_dir* (e.g. ``"extract.j2"``).
        **kwargs: Variables available in the template.

    Returns:
        Rendered prompt string.

    Raises:
        PromptRenderError: Template not found, syntax error, or undefined variable.
    """
    env = _make_env(template_dir)
    try:
        template = env.get_template(template_name)
        return template.render(**kwargs)
    except TemplateSyntaxError as e:
        raise PromptRenderError(
            f"Syntax error in template '{template_name}': {e}"
        ) from e
    except UndefinedError as e:
        raise PromptRenderError(
            f"Undefined variable in template '{template_name}': {e}"
        ) from e
    except Exception as e:
        raise PromptRenderError(
            f"Failed to render template '{template_name}': {e}"
        ) from e


def render_prompt_string(
    template_string: str,
    **kwargs: Any,
) -> str:
    """Render a Jinja2 template from a string (no file I/O).

    Args:
        template_string: Jinja2 template source.
        **kwargs: Variables available in the template.

    Returns:
        Rendered string.
    """
    env = Environment(
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    try:
        return env.from_string(template_string).render(**kwargs)
    except UndefinedError as e:
        raise PromptRenderError(f"Undefined variable in template string: {e}") from e
    except TemplateSyntaxError as e:
        raise PromptRenderError(f"Syntax error in template string: {e}") from e
