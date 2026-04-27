"""Small tracing labels for planner workflow runs."""

from __future__ import annotations

RUN_NAME_PLANNER_CREATE = "规划引擎：生成构建方案"
RUN_NAME_PLANNER_APPEND = "规划引擎：调整构建方案"


def normalize_planner_operation(operation: str) -> str:
    return str(operation or "generate_only").strip().lower() or "generate_only"


def planner_trace_run_name(operation: str) -> str:
    return RUN_NAME_PLANNER_APPEND if normalize_planner_operation(operation) == "append" else RUN_NAME_PLANNER_CREATE


__all__ = [
    "RUN_NAME_PLANNER_APPEND",
    "RUN_NAME_PLANNER_CREATE",
    "normalize_planner_operation",
    "planner_trace_run_name",
]
