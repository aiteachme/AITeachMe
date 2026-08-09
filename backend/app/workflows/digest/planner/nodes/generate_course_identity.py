"""Derive a stable course display identity from existing planner facts."""

from __future__ import annotations

import re

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.requested_structure import extract_explicit_learning_topic
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.support.courses.icons import infer_course_icon_key, normalize_course_icon_key

_AUTO_TITLE_PLACEHOLDERS = {
    "",
    "untitled course",
    "新课程",
    "无标题",
    "未命名",
    "未命名课程",
    "方案",
    "学习方案",
    "课程方案",
    "构建方案",
    "学习计划",
    "课程规划",
}
_TITLE_MAX_CHARS = 16


def _needs_auto_course_identity(state: BuildPlannerState) -> bool:
    return str(state.get("planner_operation") or "") == "create"


def _clean_course_name(value: str | None) -> str:
    raw_lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    text = raw_lines[0] if raw_lines else str(value or "").strip()
    text = " ".join(text.split())
    text = re.sub(r"^(?:标题|课程名|course_name|name)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", text)
    text = text.strip().strip("\"'“”‘’`，。；;:：.． ")
    if not text or text.casefold() in _AUTO_TITLE_PLACEHOLDERS:
        return ""
    return text[:_TITLE_MAX_CHARS].rstrip("，。；;:：.．、 ")


def _derive_course_name(state: BuildPlannerState) -> str:
    explicit_topic = extract_explicit_learning_topic(state.get("user_prompt") or "")
    if explicit_topic:
        cleaned_explicit_topic = _clean_course_name(explicit_topic)
        if cleaned_explicit_topic:
            return cleaned_explicit_topic
    material_context = state["material_context"]
    profile = material_context.learning_domain_profile
    candidates = [
        profile.sub_discipline,
        *list(profile.key_topics or []),
        *list(material_context.material_hints.chapter_candidates or []),
        profile.discipline,
    ]
    for candidate in candidates:
        cleaned = _clean_course_name(str(candidate or ""))
        if cleaned:
            return cleaned
    for packet in list(material_context.source_documents or []):
        filename = re.sub(r"\.[^.]+$", "", str(packet.filename or "").strip())
        cleaned = _clean_course_name(filename)
        if cleaned:
            return cleaned
    return "学习课程"


def build_generate_course_identity_node(*, context: WorkflowContext):
    """Build the course identity node."""

    del context

    async def generate_course_identity_node(state: BuildPlannerState) -> dict:
        if state.get("error") or not _needs_auto_course_identity(state):
            return {}

        await emit_planner_event(state, event="planner.identity.started", detail="正在整理课程名和图标。")
        course_name = _derive_course_name(state)
        course_icon = normalize_course_icon_key(infer_course_icon_key(course_name))
        await emit_planner_event(
            state,
            event="planner.identity.ready",
            detail=f"课程身份已生成：{course_name or '当前主题'}。",
            payload={"course_name": course_name, "course_icon": course_icon},
        )
        return {"generated_course_name": course_name, "generated_course_icon_key": course_icon}

    return generate_course_identity_node


__all__ = ["_clean_course_name", "_derive_course_name", "build_generate_course_identity_node"]
