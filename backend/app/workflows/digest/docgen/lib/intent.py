"""DocGen writing intent inference."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import DocGenIntentProfile
from app.workflows.digest.docgen.mode_profiles import is_sprint_docgen_mode
from app.workflows.digest.docgen.prompts.intent import build_intent_core_messages

logger = structlog.get_logger(__name__)


def fallback_intent_profile(*, digest_mode: str, chapter_count: int = 0) -> DocGenIntentProfile:
    if is_sprint_docgen_mode(digest_mode):
        return DocGenIntentProfile(
            learning_goal_text="围绕用户已确认的大纲快速建立可复习、可迁移的知识抓手。",
            audience_profile_text="学习者需要在较短时间内抓住材料主线、关键概念和可练习任务。",
            content_strategy_text="优先讲清每章最核心的判断路径、关键定义、典型例子和常见误区，避免把材料改写成纯题库。",
            example_practice_policy="例子和练习用于验证概念与方法迁移，比例略高，但不替代知识主线。",
            source_usage_policy="优先使用用户资料和已确认章节范围；外部来源只用于补足背景或缺口。",
            teaching_intent="快速建立可复习、可练习、可回看的一轮学习闭环。",
            example_ratio=0.42,
            practice_ratio=0.34,
            evidence_strictness=0.62,
            review_strictness=0.62,
            document_style="exam_sprint_notes",
            depth_level="compact",
            explanation_depth="compact",
            example_preference="many",
            definition_depth="minimal",
            exam_orientation=0.88,
            review_orientation=0.78,
            chapter_style_hints={},
            avoid_list=["不要写长篇背景", "不要把自测题伪装成真题"],
            fallback_used=True,
        )
    return DocGenIntentProfile(
        learning_goal_text="围绕用户已确认的大纲建立结构清晰、证据可追踪的系统学习文档。",
        audience_profile_text="学习者需要按章节逐步理解资料中的概念、定义、关系、例子和边界条件。",
        content_strategy_text="先搭建知识主线，再解释关键概念和依赖关系，最后用例子或练习帮助迁移。",
        example_practice_policy="例子和练习服务于理解与迁移，比例适中，避免喧宾夺主。",
        source_usage_policy="优先使用用户资料；当资料不足时才使用外部来源补充，并保留不确定性提示。",
        teaching_intent="生成一份可长期复习、可追溯来源、能支撑后续问答和图谱的学习文档。",
        example_ratio=0.30,
        practice_ratio=0.20,
        evidence_strictness=0.72,
        review_strictness=0.66,
        document_style="systematic_teaching_notes",
        depth_level="deep",
        explanation_depth="detailed",
        example_preference="balanced",
        definition_depth="strict",
        exam_orientation=0.45,
        review_orientation=0.62,
        chapter_style_hints={},
        avoid_list=["不要跳过关键定义", "不要只给结论不讲为什么"],
        fallback_used=True,
    )


async def infer_intent_core(
    *,
    course_name: str,
    digest_mode: str,
    user_prompt: str,
    plan_summary: str,
    material_profile: Mapping[str, Any],
    chapters: Sequence[Mapping[str, Any]],
    docgen_history_brief: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> DocGenIntentProfile:
    fallback = fallback_intent_profile(digest_mode=digest_mode, chapter_count=len(chapters))
    try:
        response = await acompletion_with_fallback(
            build_intent_core_messages(
                course_name=course_name,
                digest_mode=digest_mode,
                user_prompt=user_prompt,
                plan_summary=plan_summary,
                material_profile=material_profile,
                chapters=chapters,
                docgen_history_brief=docgen_history_brief,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.INTENT_CORE,
                digest_mode=digest_mode,
                extra_metadata=extra_metadata,
                docgen_stage="infer_intent_core",
            ),
            response_model=DocGenIntentProfile,
        )
    except Exception as exc:
        logger.warning("docgen_intent_core_failed", error=str(exc))
        return fallback
    if isinstance(response, DocGenIntentProfile):
        response.chapter_style_hints = {}
        response.fallback_used = False
        return response
    try:
        profile = DocGenIntentProfile.model_validate(response)
        profile.chapter_style_hints = {}
        profile.fallback_used = False
        return profile
    except Exception:
        return fallback


async def infer_docgen_intent(
    *,
    course_name: str,
    digest_mode: str,
    user_prompt: str,
    plan_summary: str,
    material_profile: Mapping[str, Any],
    chapters: Sequence[Mapping[str, Any]],
    docgen_history_brief: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> DocGenIntentProfile:
    return await infer_intent_core(
        course_name=course_name,
        digest_mode=digest_mode,
        user_prompt=user_prompt,
        plan_summary=plan_summary,
        material_profile=material_profile,
        chapters=chapters,
        docgen_history_brief=docgen_history_brief,
        extra_metadata=extra_metadata,
    )


__all__ = ["fallback_intent_profile", "infer_docgen_intent", "infer_intent_core"]
