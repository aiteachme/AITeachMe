"""Digest planner workflow lane public surface with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "BuildPlannerDraft",
    "PlannerChapterPlan",
    "append_build_planner_message",
    "build_planner_graph",
    "confirm_build_planner_session",
    "create_build_planner_session",
    "create_planner_initial_state",
    "get_confirmed_build_plan",
    "get_langgraph_dev_planner_graph",
    "get_latest_planner_session",
    "mark_confirmed_build_plan_status",
    "normalize_planner_draft",
    "normalize_planner_payload",
    "run_build_planner_workflow",
]

_ATTR_TO_MODULE = {
    "BuildPlannerDraft": "app.workflows.digest.planner.lib.plans",
    "PlannerChapterPlan": "app.workflows.digest.planner.lib.plans",
    "append_build_planner_message": "app.workflows.digest.planner.graph",
    "build_planner_graph": "app.workflows.digest.planner.graph",
    "confirm_build_planner_session": "app.workflows.digest.planner.lib.store",
    "create_build_planner_session": "app.workflows.digest.planner.graph",
    "create_planner_initial_state": "app.workflows.digest.planner.graph",
    "get_confirmed_build_plan": "app.workflows.digest.planner.lib.store",
    "get_langgraph_dev_planner_graph": "app.workflows.digest.planner.graph",
    "get_latest_planner_session": "app.workflows.digest.planner.lib.store",
    "mark_confirmed_build_plan_status": "app.workflows.digest.planner.lib.store",
    "normalize_planner_draft": "app.workflows.digest.planner.lib.plans",
    "normalize_planner_payload": "app.workflows.digest.planner.lib.plans",
    "run_build_planner_workflow": "app.workflows.digest.planner.graph",
}

_ALIASES = {
    "confirm_build_planner_session": "confirm_planner_session",
    "get_confirmed_build_plan": "get_confirmed_plan_or_raise",
    "mark_confirmed_build_plan_status": "mark_confirmed_plan_status",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, _ALIASES.get(name, name))
    globals()[name] = value
    return value
