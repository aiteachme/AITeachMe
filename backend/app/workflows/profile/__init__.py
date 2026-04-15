"""Profile workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "MasteryAttempt",
    "MasteryUpdateResult",
    "ProfileWorkflowState",
    "PROMPTS",
    "SYSTEM_PROMPT_REPORT_SUGGESTIONS",
    "WeaknessItem",
    "analyze_weakness",
    "build_profile_pipeline_graph",
    "build_profile_workflow_graph",
    "compute_confidence_score",
    "compute_mastery_score",
    "compute_sm2_interval",
    "compute_stability_score",
    "create_profile_initial_state",
    "generate_report_suggestions",
    "schedule_reviews",
    "update_mastery_from_exam",
]

_ATTR_TO_MODULE = {
    "MasteryAttempt": "app.workflows.profile.mastery_updater",
    "MasteryUpdateResult": "app.workflows.profile.mastery_updater",
    "ProfileWorkflowState": "app.workflows.profile.state",
    "PROMPTS": "app.workflows.profile.prompts",
    "SYSTEM_PROMPT_REPORT_SUGGESTIONS": "app.workflows.profile.prompts",
    "WeaknessItem": "app.workflows.profile.weakness_analyzer",
    "analyze_weakness": "app.workflows.profile.weakness_analyzer",
    "build_profile_pipeline_graph": "app.workflows.profile.graph",
    "build_profile_workflow_graph": "app.workflows.profile.graph",
    "compute_confidence_score": "app.workflows.profile.mastery_updater",
    "compute_mastery_score": "app.workflows.profile.mastery_updater",
    "compute_sm2_interval": "app.workflows.profile.review_scheduler",
    "compute_stability_score": "app.workflows.profile.mastery_updater",
    "create_profile_initial_state": "app.workflows.profile.graph",
    "generate_report_suggestions": "app.workflows.profile.runtime",
    "schedule_reviews": "app.workflows.profile.review_scheduler",
    "update_mastery_from_exam": "app.workflows.profile.mastery_updater",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
