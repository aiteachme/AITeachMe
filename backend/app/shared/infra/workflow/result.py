"""Workflow 返回结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class WorkflowError(Exception):
    """Workflow 统一错误对象。"""

    code: str
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.detail


@dataclass(slots=True)
class WorkflowResult(Generic[T]):
    """Workflow 统一返回结构。"""

    value: T | None = None
    error: WorkflowError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def failed(self) -> bool:
        return self.error is not None

    def require_value(self) -> T:
        """返回成功结果，否则抛错。"""

        if self.error is not None or self.value is None:
            raise self.error or WorkflowError(
                code="workflow_result_missing",
                detail="Workflow 未返回有效结果。",
            )
        return self.value


def ok_result(value: T) -> WorkflowResult[T]:
    """构造成功结果。"""

    return WorkflowResult(value=value)


def err_result(
    code: str,
    detail: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> WorkflowResult[T]:
    """构造失败结果。"""

    return WorkflowResult(error=WorkflowError(code=code, detail=detail, metadata=metadata or {}))

