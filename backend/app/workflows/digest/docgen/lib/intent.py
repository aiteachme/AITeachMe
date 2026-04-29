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
