"""Stable workflow entry points for examine recovery services."""

from __future__ import annotations


async def run_exam_grading_recovery_loop(*, task_registry) -> None:
    # Compatibility bridge while the grading runner remains in the legacy API
    # module. main.py depends only on this workflow entry point.
    from app.api.exams import run_exam_grading_recovery_loop as legacy_loop

    await legacy_loop(task_registry=task_registry)


__all__ = ["run_exam_grading_recovery_loop"]
