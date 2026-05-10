"""Legacy Profile pipeline compatibility package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ProfileWorkflowState",
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

_ATTR_TO_MODULE = {
    "ProfileWorkflowState": "app.workflows.profile.pipeline.state",
    "WORKFLOW_EXPORTS": "app.workflows.profile.pipeline.graph",
    "build_profile_pipeline_graph": "app.workflows.profile.pipeline.graph",
    "build_profile_snapshot_graph": "app.workflows.profile.pipeline.graph",
    "build_profile_workflow_graph": "app.workflows.profile.pipeline.graph",
    "create_profile_initial_state": "app.workflows.profile.pipeline.graph",
    "create_profile_snapshot_initial_state": "app.workflows.profile.pipeline.graph",
    "get_langgraph_dev_profile_pipeline_graph": "app.workflows.profile.pipeline.graph",
    "get_langgraph_dev_profile_snapshot_graph": "app.workflows.profile.pipeline.graph",
    "get_langgraph_dev_profile_study_plan_graph": "app.workflows.profile.pipeline.graph",
    "run_profile_pipeline_workflow": "app.workflows.profile.pipeline.graph",
    "run_profile_snapshot_workflow": "app.workflows.profile.pipeline.graph",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
