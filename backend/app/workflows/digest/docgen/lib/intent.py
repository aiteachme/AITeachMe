"""DocGen writing intent inference."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import DocGenIntentProfile
from app.workflows.digest.docgen.prompts.intent import build_intent_core_messages

logger = structlog.get_logger(__name__)


class DocGenIntentError(RuntimeError):
    """Raised when the LLM cannot infer a usable DocGen intent profile."""


async def infer_intent_core(
    *,
    course_name: str,
    digest_mode: str,
    user_prompt: str,
    plan: str,
    material_profile: Mapping[str, Any],
    chapters: Sequence[Mapping[str, Any]],
    docgen_history_brief: str = "",
    learner_profile_text: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> DocGenIntentProfile:
    try:
        response = await acompletion_with_fallback(
            build_intent_core_messages(
                course_name=course_name,
                digest_mode=digest_mode,
                user_prompt=user_prompt,
                plan=plan,
                material_profile=material_profile,
                chapters=chapters,
                docgen_history_brief=docgen_history_brief,
                learner_profile_text=learner_profile_text,
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
        raise DocGenIntentError("LLM failed to infer DocGen intent after configured retries.") from exc
    try:
        profile = response if isinstance(response, DocGenIntentProfile) else DocGenIntentProfile.model_validate(response)
    except Exception as exc:
        raise DocGenIntentError("LLM returned an invalid DocGen intent schema.") from exc
    profile.chapter_style_hints = {}
    profile.fallback_used = False
    return profile


async def infer_docgen_intent(
    *,
    course_name: str,
    digest_mode: str,
    user_prompt: str,
    plan: str,
    material_profile: Mapping[str, Any],
    chapters: Sequence[Mapping[str, Any]],
    docgen_history_brief: str = "",
    learner_profile_text: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> DocGenIntentProfile:
    return await infer_intent_core(
        course_name=course_name,
        digest_mode=digest_mode,
        user_prompt=user_prompt,
        plan=plan,
        material_profile=material_profile,
        chapters=chapters,
        docgen_history_brief=docgen_history_brief,
        learner_profile_text=learner_profile_text,
        extra_metadata=extra_metadata,
    )


__all__ = ["DocGenIntentError", "infer_docgen_intent", "infer_intent_core"]
