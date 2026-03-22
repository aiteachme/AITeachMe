"""State types for the profile workflow package."""

from __future__ import annotations

from typing import TypedDict


class ProfileWorkflowState(TypedDict, total=False):
    mastery_updated: bool
    review_scheduled: bool
    weaknesses_ranked: bool
    report_generated: bool
