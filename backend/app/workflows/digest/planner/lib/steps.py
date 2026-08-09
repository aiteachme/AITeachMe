"""Planner graph node ids, display names, and runtime timing fields."""

from __future__ import annotations

STEP_LOAD_MATERIALS = "collect_planner_context"
STEP_COMPOSE_PLAN = "compose_planner_draft"
STEP_SAVE_PLAN = "save_planner_draft"

STEP_DISPLAY_NAMES = {
    STEP_LOAD_MATERIALS: "汇总会话与资料上下文",
    STEP_COMPOSE_PLAN: "生成方案草案",
    STEP_SAVE_PLAN: "保存方案草案",
}

STEP_TIMING_FIELDS = (
    (STEP_LOAD_MATERIALS, "prepare_ms"),
    (STEP_COMPOSE_PLAN, "compose_ms"),
    (STEP_SAVE_PLAN, "finalize_ms"),
)


__all__ = [
    "STEP_COMPOSE_PLAN",
    "STEP_DISPLAY_NAMES",
    "STEP_LOAD_MATERIALS",
    "STEP_SAVE_PLAN",
    "STEP_TIMING_FIELDS",
]
