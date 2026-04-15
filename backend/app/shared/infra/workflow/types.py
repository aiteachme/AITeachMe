"""Shared workflow type aliases and lightweight schema helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, TypedDict, cast

StateT = TypeVar("StateT")

AsyncNode = Callable[[StateT], Awaitable[StateT]]
GraphBuilder = Callable[[], Any]


def project_typed_dict_schema(
    state_type: type,
    *,
    name: str,
    fields: list[str] | tuple[str, ...],
) -> type:
    """Build a thin TypedDict schema by projecting fields from one state type.

    This keeps the workflow state as the single source of truth while still
    letting LangGraph Studio expose a compact input/output form.
    """

    annotations = getattr(state_type, "__annotations__", {})
    missing = [field for field in fields if field not in annotations]
    if missing:
        missing_fields = ", ".join(sorted(missing))
        raise KeyError(f"{name} references unknown state fields: {missing_fields}")

    projected_annotations = {field: annotations[field] for field in fields}
    return cast(type, TypedDict(name, projected_annotations, total=False))
