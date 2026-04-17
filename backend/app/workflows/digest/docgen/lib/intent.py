"""DocGen writing intent inference."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.workflows.digest.docgen.lib.models import DocGenIntentProfile
from app.workflows.digest.docgen.prompts.intent import build_intent_messages

logger = structlog.get_logger(__name__)


def fallback_intent_profile(*, digest_mode: str, chapter_count: int = 0) -> DocGenIntentProfile:
    normalized_mode = str(digest_mode or "").strip().lower()
    if normalized_mode == "sprint":
        return DocGenIntentProfile(
            document_style="exam_sprint_notes",
            depth_level="compact",
            explanation_depth="compact",
            example_preference="many",
            definition_depth="minimal",
            exam_orientation=0.88,
            review_orientation=0.78,
            chapter_style_hints={index: "先抓考点，再讲题型和易错点。" for index in range(1, chapter_count + 1)},
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
        chapter_style_hints={index: "先讲定义和结构，再展开推理、例子与迁移。" for index in range(1, chapter_count + 1)},
        avoid_list=["不要跳过关键定义", "不要只给结论不讲为什么"],
        fallback_used=True,
    )


async def infer_docgen_intent(
    *,
    subject: str,
    digest_mode: str,
    user_goal: str,
    plan_summary: str,
    material_profile: Mapping[str, Any],
    chapters: Sequence[Mapping[str, Any]],
    extra_metadata: Mapping[str, Any] | None = None,
) -> DocGenIntentProfile:
    fallback = fallback_intent_profile(digest_mode=digest_mode, chapter_count=len(chapters))
    try:
        response = await acompletion_with_fallback(
            build_intent_messages(
                subject=subject,
                digest_mode=digest_mode,
                user_goal=user_goal,
                plan_summary=plan_summary,
                material_profile=material_profile,
                chapters=chapters,
            ),
            task_type=TaskType.CLASSIFY,
            model="primary",
            response_model=DocGenIntentProfile,
            temperature=0.1,
            max_tokens=900,
            extra_metadata={"docgen_stage": "infer_docgen_intent", **dict(extra_metadata or {})},
        )
    except Exception as exc:
        logger.warning("docgen_intent_inference_failed", error=str(exc))
        return fallback
    if isinstance(response, DocGenIntentProfile):
        response.fallback_used = False
        return response
    try:
        profile = DocGenIntentProfile.model_validate(response)
        profile.fallback_used = False
        return profile
    except Exception:
        return fallback


__all__ = ["fallback_intent_profile", "infer_docgen_intent"]
