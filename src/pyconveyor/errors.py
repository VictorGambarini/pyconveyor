"""Typed exceptions with YAML location context."""
from __future__ import annotations


class PyConveyorError(Exception):
    """Base exception for all pyconveyor errors."""


class PipelineLoadError(PyConveyorError):
    """Raised when a pipeline YAML file cannot be loaded or is invalid."""

    def __init__(
        self,
        message: str,
        file: str | None = None,
        line: int | None = None,
        key_path: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        self.file = file
        self.line = line
        self.key_path = key_path
        self.suggestion = suggestion

        parts: list[str] = []
        if file:
            loc = file
            if line:
                loc += f":{line}"
            parts.append(loc)
        if key_path:
            parts.append(f"  {key_path}")
        if parts:
            parts.append(f"  {message}")
        else:
            parts.append(message)
        if suggestion:
            parts.append(f"  Did you mean: {suggestion!r}?")

        super().__init__("\n".join(parts))


class ExpressionSecurityError(PipelineLoadError):
    """Raised when an expression contains disallowed AST nodes."""


class ExpressionEvalError(PyConveyorError):
    """Raised when an expression fails to evaluate at runtime."""


class StepConfigError(PipelineLoadError):
    """Raised when a step configuration is invalid."""


class CallableImportError(PipelineLoadError):
    """Raised when a fn:, schema:, or parser: reference cannot be imported."""


class SchemaRefError(PipelineLoadError):
    """Raised when a schema: reference does not resolve to a Pydantic BaseModel."""


class ModelRefError(PipelineLoadError):
    """Raised when a model: reference is not defined in the models: block."""


class StepRefError(PipelineLoadError):
    """Raised when a step name referenced in an expression is not defined."""


class StepExecutionError(PyConveyorError):
    """Raised when a step fails during execution."""

    def __init__(
        self,
        step_name: str,
        message: str,
        cause: BaseException | None = None,
    ) -> None:
        self.step_name = step_name
        self.cause = cause
        super().__init__(f"Step '{step_name}' failed: {message}")


class ParseError(PyConveyorError):
    """Raised when a model response cannot be parsed as JSON."""


class SchemaValidationError(PyConveyorError):
    """Raised when a parsed response fails Pydantic schema validation."""

    def __init__(self, message: str, validation_error: Exception | None = None) -> None:
        self.validation_error = validation_error
        super().__init__(message)


class PromptTooLargeError(PyConveyorError):
    """Raised when a rendered prompt exceeds max_prompt_tokens."""

    def __init__(self, step_name: str, token_count: int, limit: int) -> None:
        self.step_name = step_name
        self.token_count = token_count
        self.limit = limit
        super().__init__(
            f"Step '{step_name}': prompt has ~{token_count} tokens, exceeds limit of {limit}"
        )


class PipelineAbortError(PyConveyorError):
    """Raised when on_error=raise and a step exhausts its retry budget."""

    def __init__(self, step_name: str, cause: BaseException) -> None:
        self.step_name = step_name
        self.cause = cause
        super().__init__(f"Pipeline aborted at step '{step_name}': {cause}")
