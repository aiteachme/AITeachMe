"""Profile graph terminal nodes.

Terminal nodes keep failure state visible to LangSmith and callers. They do
not hide or recover errors.
"""

from __future__ import annotations

from app.workflows.profile.common.state import ProfileWorkflowState


def fail_profile_lane_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
    """Return the failed state unchanged for traceable graph completion."""

    return state


__all__ = ["fail_profile_lane_node"]
