"""Knowledge docs domain service entrypoints."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "append_build_planner_message_service": "build_planner_service",
    "clear_subject_knowledge": "cleanup_service",
    "confirm_build_planner_session_service": "build_planner_service",
    "create_build_planner_session_service": "build_planner_service",
    "get_docgen_result": "digest_service",
    "get_confirmed_build_plan_service": "build_planner_service",
    "get_knowledge_overview": "overview_service",
    "get_latest_planner_session_service": "build_planner_service",
    "handle_study_plan_request": "study_plan_service",
    "mark_confirmed_build_plan_status": "build_planner_service",
    "run_docgen_background": "digest_service",
    "run_unified_build_background": "digest_service",
    "trigger_docgen_build": "digest_service",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value
