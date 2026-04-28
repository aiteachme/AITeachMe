"""Profile workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "MasteryUpdateResult",
    "ProfileWorkflowState",
    "PROMPTS",
    "SYSTEM_PROMPT_REPORT_SUGGESTIONS",
    "SubjectProfileSummary",
    "UserProfileSummary",
    "WeaknessItem",
    "analyze_weakness",
    "build_profile_pipeline_graph",
    "build_profile_workflow_graph",
    "build_subject_profile_summary",
    "build_user_profile_summary",
    "compute_confidence_score",
    "compute_sm2_interval",
    "compute_stability_score",
    "create_profile_initial_state",
    "generate_report_suggestions",
    "schedule_reviews",
    "update_mastery_from_exam",
    "WORKFLOW_EXPORTS",
]

_ATTR_TO_MODULE = {
    "MasteryUpdateResult": "app.workflows.profile.pipeline.lib",
    "ProfileWorkflowState": "app.workflows.profile.pipeline.state",
    "PROMPTS": "app.workflows.profile.pipeline.prompts",
    "SYSTEM_PROMPT_REPORT_SUGGESTIONS": "app.workflows.profile.pipeline.prompts",
    "SubjectProfileSummary": "app.schemas.profile",
    "UserProfileSummary": "app.schemas.profile",
    "WeaknessItem": "app.workflows.profile.pipeline.lib",
    "WORKFLOW_EXPORTS": "app.workflows.profile.pipeline.graph",
    "analyze_weakness": "app.workflows.profile.pipeline.lib",
    "build_profile_pipeline_graph": "app.workflows.profile.pipeline.graph",
    "build_profile_workflow_graph": "app.workflows.profile.pipeline.graph",
    "build_subject_profile_summary": "app.workflows.profile.pipeline.lib",
    "build_user_profile_summary": "app.workflows.profile.pipeline.lib",
    "compute_confidence_score": "app.workflows.profile.pipeline.lib",
    "compute_sm2_interval": "app.workflows.profile.pipeline.lib",
    "compute_stability_score": "app.workflows.profile.pipeline.lib",
    "create_profile_initial_state": "app.workflows.profile.pipeline.graph",
    "generate_report_suggestions": "app.workflows.profile.pipeline.lib",
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
