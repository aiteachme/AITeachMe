"""Planner graph node ids, display names, and runtime timing fields."""

from __future__ import annotations

STEP_LOAD_MATERIALS = "load_planner_materials"
STEP_UNDERSTAND_GOAL = "stream_brief_and_extract_intent"
STEP_COMPOSE_PLAN = "stream_and_parse_plan_draft"
STEP_GENERATE_TITLE = "generate_course_name"
STEP_SAVE_PLAN = "normalize_and_persist_plan"

STEP_DISPLAY_NAMES = {
    STEP_LOAD_MATERIALS: "读取资料",
    STEP_UNDERSTAND_GOAL: "理解目标",
    STEP_COMPOSE_PLAN: "合成大纲",
    STEP_GENERATE_TITLE: "生成标题",
    STEP_SAVE_PLAN: "保存方案",
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
