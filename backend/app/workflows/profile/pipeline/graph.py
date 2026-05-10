"""Compatibility exports for the legacy Profile pipeline lane name.

New code should import from ``profile.update``, ``profile.snapshot``, or
``profile.study_plan``. This module keeps old pipeline imports working while
the project finishes the lane split.
"""

from __future__ import annotations

from app.workflows.profile.snapshot.graph import (
    build_profile_snapshot_graph,
    create_profile_snapshot_initial_state,
    get_langgraph_dev_profile_snapshot_graph,
    run_profile_snapshot_workflow,
)
from app.workflows.profile.study_plan.graph import (
    get_langgraph_dev_profile_study_plan_graph,
)
from app.workflows.profile.update.graph import (
    PROFILE_UPDATE_WORKFLOW_NAME,
    WORKFLOW_EXPORTS as UPDATE_WORKFLOW_EXPORTS,
    build_profile_update_graph,
    create_profile_update_initial_state,
    get_langgraph_dev_profile_update_graph,
    run_profile_update_workflow,
)
from app.workflows.profile.snapshot.graph import WORKFLOW_EXPORTS as SNAPSHOT_WORKFLOW_EXPORTS
from app.workflows.profile.study_plan.graph import WORKFLOW_EXPORTS as STUDY_PLAN_WORKFLOW_EXPORTS

PROFILE_PIPELINE_WORKFLOW_NAME = PROFILE_UPDATE_WORKFLOW_NAME
PROFILE_SNAPSHOT_WORKFLOW_NAME = "profile.snapshot"

build_profile_pipeline_graph = build_profile_update_graph
build_profile_workflow_graph = build_profile_update_graph
create_profile_initial_state = create_profile_update_initial_state
get_langgraph_dev_profile_pipeline_graph = get_langgraph_dev_profile_update_graph
run_profile_pipeline_workflow = run_profile_update_workflow

WORKFLOW_EXPORTS = (
    *UPDATE_WORKFLOW_EXPORTS,
    *SNAPSHOT_WORKFLOW_EXPORTS,
    *STUDY_PLAN_WORKFLOW_EXPORTS,
)

__all__ = [
    "PROFILE_PIPELINE_WORKFLOW_NAME",
    "PROFILE_SNAPSHOT_WORKFLOW_NAME",
    "WORKFLOW_EXPORTS",
    "build_profile_pipeline_graph",
    "build_profile_snapshot_graph",
    "build_profile_workflow_graph",
    "create_profile_initial_state",
    "create_profile_snapshot_initial_state",
    "get_langgraph_dev_profile_pipeline_graph",
    "get_langgraph_dev_profile_snapshot_graph",
    "get_langgraph_dev_profile_study_plan_graph",
    "run_profile_pipeline_workflow",
    "run_profile_snapshot_workflow",
]
