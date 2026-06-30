"""Generate course display identity for a new planner session."""

from __future__ import annotations

import re

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.model_policy import (
    PlannerModelStep,
    planner_completion_kwargs_with_metadata,
)
from app.workflows.digest.planner.lib.models import PlannerCourseIdentity
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.requested_structure import extract_explicit_learning_topic
from app.workflows.digest.planner.prompts.course_name import build_course_identity_messages
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.support.courses.icons import infer_course_icon_key, normalize_course_icon_key

logger = structlog.get_logger(__name__)

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


def _collect_topic_hints(state: BuildPlannerState) -> list[str]:
    material_context = state["material_context"]
    raw_items = [
        *list(material_context.material_hints.chapter_candidates or []),
        *list(material_context.learning_domain_profile.key_topics or []),
    ]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = " ".join(str(item or "").split()).strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def build_generate_course_identity_node(*, context: WorkflowContext):
    """Build the course identity node."""

    del context

    async def generate_course_identity_node(state: BuildPlannerState) -> dict:
        if state.get("error") or not _needs_auto_course_identity(state):
            return {}

        material_context = state["material_context"]
        filenames = [
            packet.filename
            for packet in list(material_context.source_documents or [])
            if str(packet.filename or "").strip()
        ]
        topic_hints = _collect_topic_hints(state)
        planning_note = str(state.get("planning_note") or "").strip()
        material_note = str(state.get("material_note") or "").strip()
        await emit_planner_event(state, event="planner.identity.started", detail="正在生成课程名和图标。")
        try:
            result = await acompletion_with_fallback(
                build_course_identity_messages(
                    user_prompt=state.get("user_prompt") or "",
                    filenames=filenames,
                    digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                    planning_note=planning_note,
                    material_note=material_note,
                    topic_hints=topic_hints,
                ),
                **planner_completion_kwargs_with_metadata(
                    PlannerModelStep.COURSE_IDENTITY,
                    model_override=state.get("model_override"),
                    planner_session_id=state.get("planner_session_id") or "",
                    substep="生成 course_name 与 course_icon",
                ),
                response_model=PlannerCourseIdentity,
            )
        except Exception as exc:
            logger.exception(
                "planner_course_identity_generation_failed",
                planner_session_id=state.get("planner_session_id") or "",
                course_id=state.get("course_id") or "",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            await emit_planner_event(
                state,
                event="planner.identity.failed",
                detail="课程名和图标生成失败，请重试。",
                payload={"error_type": type(exc).__name__},
            )
            raise

        identity = result if isinstance(result, PlannerCourseIdentity) else PlannerCourseIdentity.model_validate(result)
        explicit_topic = extract_explicit_learning_topic(state.get("user_prompt") or "")
        course_name = explicit_topic or _clean_course_name(identity.course_name)
        course_icon = normalize_course_icon_key(identity.course_icon) or infer_course_icon_key(course_name)
        await emit_planner_event(
            state,
            event="planner.identity.ready",
            detail=f"课程身份已生成：{course_name or '当前主题'}。",
            payload={"course_name": course_name, "course_icon": course_icon},
        )
        logger.info(
            "planner_course_identity_generation_completed",
            planner_session_id=state.get("planner_session_id") or "",
            course_id=state.get("course_id") or "",
            generated_course_name=course_name or None,
            generated_course_icon_key=course_icon or None,
        )
        return {"generated_course_name": course_name, "generated_course_icon_key": course_icon}

    return generate_course_identity_node


__all__ = ["_clean_course_name", "build_generate_course_identity_node"]
