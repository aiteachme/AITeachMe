"""State types for the profile workflow."""

from __future__ import annotations

from typing import TypedDict


class ProfileWorkflowState(TypedDict, total=False):
    aggregated: bool
    reported: bool
