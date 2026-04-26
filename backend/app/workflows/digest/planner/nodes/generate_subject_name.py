"""Generate a short planner subject title in parallel with plan composition."""

from __future__ import annotations

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.model_policy import (
    PlannerModelStep,
    planner_completion_kwargs_with_metadata,
)
from app.workflows.digest.planner.lib.models import PlanIntent, PlannerBrief
from app.workflows.digest.planner.prompts.subject_name import build_subject_name_prompt
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.support.subjects.icons import choose_subject_icon_key

logger = structlog.get_logger(__name__)

_AUTO_TITLE_PLACEHOLDERS = {"", "untitled subject", "新学科", "无标题", "未命名", "未命名学科"}


def _needs_auto_subject_name(state: BuildPlannerState) -> bool:
    return str(state.get("planner_operation") or "") == "create"


def _clean_subject_name(value: str | None) -> str:
    cleaned = str(value or "").strip().strip("\"'“”‘’`，。；;:： ")
    cleaned = " ".join(cleaned.split())
    if not cleaned or cleaned.casefold() in _AUTO_TITLE_PLACEHOLDERS:
        return ""
    return cleaned


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


def build_generate_subject_name_node(*, context: WorkflowContext):
    """构建标题生成节点。

    标题生成只依赖 brief / intent / 资料线索，不依赖最终大纲草稿，
    因此应和 stream_and_parse_plan_draft 并行执行，而不是串在保存节点里。
    """

    del context

    async def generate_subject_name_node(state: BuildPlannerState) -> dict:
        if state.get("error") or not _needs_auto_subject_name(state):
            return {}

        material_context = state["material_context"]
        planner_brief = PlannerBrief.model_validate(state.get("planner_brief") or {})
        plan_intent = PlanIntent.model_validate(state.get("plan_intent") or {})
        filenames = [
            packet.filename
            for packet in list(material_context.source_documents or [])
            if str(packet.filename or "").strip()
        ]
        topic_hints = _collect_topic_hints(state)
        prompt = build_subject_name_prompt(
            user_prompt=state.get("user_prompt") or "",
            filenames=filenames,
            digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
            plan_intent=plan_intent.plan_intent,
            planner_brief=planner_brief.markdown,
            topic_hints=topic_hints,
        )
        try:
            logger.info(
                "planner_subject_name_generation_started",
                planner_session_id=state.get("planner_session_id") or "",
                subject=state.get("subject") or "",
                topic_hint_count=len(topic_hints),
            )
            title = await acompletion_with_fallback(
                [{"role": "user", "content": prompt}],
                **planner_completion_kwargs_with_metadata(
                    PlannerModelStep.SUBJECT_NAME,
                    planner_session_id=state.get("planner_session_id") or "",
                    substep="生成学科标题",
                ),
            )
        except Exception:
            logger.exception(
                "planner_subject_name_generation_failed",
                planner_session_id=state.get("planner_session_id") or "",
                subject=state.get("subject") or "",
            )
            return {"generated_subject_name": "", "generated_subject_icon_key": ""}

        cleaned = _clean_subject_name(title)
        logger.info(
            "planner_subject_name_generation_completed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state.get("subject") or "",
            generated_subject_name=cleaned or None,
        )
        icon_key = (
            await choose_subject_icon_key(
                cleaned,
                hints=topic_hints,
                completion_kwargs=planner_completion_kwargs_with_metadata(
                    PlannerModelStep.SUBJECT_ICON,
                    planner_session_id=state.get("planner_session_id") or "",
                    substep="选择学科图标",
                ),
            )
            if cleaned
            else ""
        )
        return {"generated_subject_name": cleaned, "generated_subject_icon_key": icon_key}

    return generate_subject_name_node


__all__ = ["build_generate_subject_name_node"]
