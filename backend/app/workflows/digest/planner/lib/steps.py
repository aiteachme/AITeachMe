"""Planner graph node ids, display names, and runtime timing fields."""

from __future__ import annotations

STEP_LOAD_MATERIALS = "collect_planner_context"
STEP_UNDERSTAND_GOAL = "understand_goal_and_materials"
STEP_COMPOSE_PLAN = "compose_planner_draft"
STEP_GENERATE_TITLE = "generate_course_identity"
STEP_SAVE_PLAN = "save_planner_draft"

STEP_DISPLAY_NAMES = {
    STEP_LOAD_MATERIALS: "汇总会话与资料上下文",
    STEP_UNDERSTAND_GOAL: "理解学习目标与资料",
    STEP_COMPOSE_PLAN: "生成方案草案",
    STEP_GENERATE_TITLE: "生成课程展示身份",
    STEP_SAVE_PLAN: "保存方案草案",
}

STEP_TIMING_FIELDS = (
    (STEP_LOAD_MATERIALS, "prepare_ms"),
    (STEP_UNDERSTAND_GOAL, "bootstrap_ms"),
    (STEP_COMPOSE_PLAN, "compose_ms"),
    (STEP_GENERATE_TITLE, "title_ms"),
    (STEP_SAVE_PLAN, "finalize_ms"),
)


__all__ = [
    "STEP_COMPOSE_PLAN",
    "STEP_DISPLAY_NAMES",
    "STEP_GENERATE_TITLE",
    "STEP_LOAD_MATERIALS",
    "STEP_SAVE_PLAN",
    "STEP_TIMING_FIELDS",
    "STEP_UNDERSTAND_GOAL",
]
