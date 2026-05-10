"""Profile graph terminal nodes.

Terminal nodes keep failure state visible to LangSmith and callers. They do
not hide or recover errors.
"""

from __future__ import annotations

from app.workflows.profile.pipeline.state import ProfileWorkflowState


def fail_profile_pipeline_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
    """Return the failed state unchanged for traceable graph completion."""

    return state


__all__ = ["fail_profile_pipeline_node"]
