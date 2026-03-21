"""State types for the interact workflow."""

from __future__ import annotations

from typing import TypedDict


class InteractWorkflowState(TypedDict, total=False):
    retrieved: bool
    responded: bool
