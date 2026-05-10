"""Profile workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "MasteryUpdateResult",
    "ProfileSnapshotState",
    "ProfileStudyPlanState",
    "ProfileUpdateState",
    "ProfileWorkflowState",
    "PROMPTS",
    "SYSTEM_PROMPT_REPORT_SUGGESTIONS",
    "CourseProfileSummary",
    "UserProfileSummary",
    "WeaknessItem",
    "analyze_weakness",
    "build_profile_pipeline_graph",
    "build_profile_snapshot_graph",
    "build_profile_study_plan_graph",
    "build_profile_update_graph",
    "build_profile_workflow_graph",
    "build_course_profile_summary",
    "build_user_profile_summary",
    "compute_confidence_score",
    "compute_sm2_interval",
    "compute_stability_score",
    "create_profile_initial_state",
    "create_profile_snapshot_initial_state",
    "create_profile_study_plan_initial_state",
    "create_profile_update_initial_state",
    "generate_report_suggestions",
    "get_langgraph_dev_profile_pipeline_graph",
    "get_langgraph_dev_profile_snapshot_graph",
    "get_langgraph_dev_profile_study_plan_graph",
    "get_langgraph_dev_profile_update_graph",
    "run_profile_pipeline_workflow",
    "run_profile_snapshot_workflow",
    "run_profile_study_plan_workflow",
    "run_profile_update_workflow",
    "schedule_reviews",
    "update_mastery_from_exam",
    "WORKFLOW_EXPORTS",
]

_ATTR_TO_MODULE = {
    "MasteryUpdateResult": "app.workflows.profile.pipeline.lib",
    "ProfileSnapshotState": "app.workflows.profile.snapshot.state",
    "ProfileStudyPlanState": "app.workflows.profile.study_plan.state",
    "ProfileUpdateState": "app.workflows.profile.update.state",
    "ProfileWorkflowState": "app.workflows.profile.pipeline.state",
    "PROMPTS": "app.workflows.profile.pipeline.prompts",
    "SYSTEM_PROMPT_REPORT_SUGGESTIONS": "app.workflows.profile.pipeline.prompts",
    "CourseProfileSummary": "app.schemas.profile",
    "UserProfileSummary": "app.schemas.profile",
    "WeaknessItem": "app.workflows.profile.pipeline.lib",
    "WORKFLOW_EXPORTS": "app.workflows.profile.pipeline.graph",
    "analyze_weakness": "app.workflows.profile.pipeline.lib",
    "build_profile_pipeline_graph": "app.workflows.profile.pipeline.graph",
    "build_profile_snapshot_graph": "app.workflows.profile.snapshot.graph",
    "build_profile_study_plan_graph": "app.workflows.profile.study_plan.graph",
    "build_profile_update_graph": "app.workflows.profile.update.graph",
    "build_profile_workflow_graph": "app.workflows.profile.pipeline.graph",
    "build_course_profile_summary": "app.workflows.profile.pipeline.lib",
    "build_user_profile_summary": "app.workflows.profile.pipeline.lib",
    "compute_confidence_score": "app.workflows.profile.pipeline.lib",
    "compute_sm2_interval": "app.workflows.profile.pipeline.lib",
    "compute_stability_score": "app.workflows.profile.pipeline.lib",
    "create_profile_initial_state": "app.workflows.profile.pipeline.graph",
    "create_profile_snapshot_initial_state": "app.workflows.profile.snapshot.graph",
    "create_profile_study_plan_initial_state": "app.workflows.profile.study_plan.graph",
    "create_profile_update_initial_state": "app.workflows.profile.update.graph",
    "generate_report_suggestions": "app.workflows.profile.pipeline.lib",
    "get_langgraph_dev_profile_pipeline_graph": "app.workflows.profile.pipeline.graph",
    "get_langgraph_dev_profile_snapshot_graph": "app.workflows.profile.snapshot.graph",
    "get_langgraph_dev_profile_study_plan_graph": "app.workflows.profile.study_plan.graph",
    "get_langgraph_dev_profile_update_graph": "app.workflows.profile.update.graph",
    "run_profile_pipeline_workflow": "app.workflows.profile.pipeline.graph",
    "run_profile_snapshot_workflow": "app.workflows.profile.snapshot.graph",
    "run_profile_study_plan_workflow": "app.workflows.profile.study_plan.graph",
    "run_profile_update_workflow": "app.workflows.profile.update.graph",
    "schedule_reviews": "app.workflows.profile.pipeline.lib",
    "update_mastery_from_exam": "app.workflows.profile.pipeline.lib",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
