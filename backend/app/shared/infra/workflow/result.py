"""Workflow result contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class WorkflowError(Exception):
    """Shared workflow error payload."""

    code: str
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.detail


@dataclass(slots=True)
class WorkflowResult(Generic[T]):
    """Shared workflow result wrapper."""

    value: T | None = None
    error: WorkflowError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def failed(self) -> bool:
        return self.error is not None

    def require_value(self) -> T:
        """Return the successful value or raise a workflow error."""

        if self.error is not None or self.value is None:
            raise self.error or WorkflowError(
                code="workflow_result_missing",
                detail="Workflow did not return a value.",
            )
        return self.value


def ok_result(value: T) -> WorkflowResult[T]:
    """Build a successful workflow result."""

    return WorkflowResult(value=value)


def err_result(
    code: str,
    detail: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> WorkflowResult[T]:
    """Build a failed workflow result."""

    return WorkflowResult(error=WorkflowError(code=code, detail=detail, metadata=metadata or {}))
