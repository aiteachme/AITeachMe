"""State types for the examine workflow."""

from __future__ import annotations

from typing import TypedDict


class ExamineWorkflowState(TypedDict, total=False):
    prepared: bool
    graded: bool
