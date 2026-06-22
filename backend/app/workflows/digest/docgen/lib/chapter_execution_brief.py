"""Chapter-level execution brief generation for DocGen."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

import structlog

from app.shared.infra.env_support import get_env_bounded_float
from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import ChapterExecutionBrief, clean_string_list
from app.workflows.digest.docgen.prompts.chapter_execution_brief import build_chapter_execution_brief_messages

logger = structlog.get_logger(__name__)


class ChapterExecutionBriefError(RuntimeError):
    """Raised when the LLM cannot produce a usable chapter execution brief."""


def _chapter_brief_timeout_seconds() -> float:
    return get_env_bounded_float(
        "DOCGEN_CHAPTER_EXECUTION_BRIEF_TIMEOUT_S",
        45.0,
        min_value=5.0,
        max_value=180.0,
    )


async def build_chapter_execution_brief(
    *,
    course_name: str,
    digest_mode: str,
    chapter: Mapping[str, object],
    locked_title: str,
    intent_core: Mapping[str, object],
    glossary_terms: Sequence[str],
    claim_targets: Sequence[str],
    confusion_targets: Sequence[str],
    source_slices: Sequence[Mapping[str, object]] = (),
    evidence_items: Sequence[Mapping[str, object]] = (),
    plan: str = "",
    docgen_history_brief: str = "",
    learner_profile_text: str = "",
    extra_metadata: Mapping[str, object] | None = None,
) -> ChapterExecutionBrief:
    chapter_index = int(chapter.get("chapter_index", 0) or 0) or 1

    async def _run_chapter_brief(_: object) -> object:
        return await acompletion_with_fallback(
            build_chapter_execution_brief_messages(
                course_name=course_name,
                digest_mode=digest_mode,
                chapter=chapter,
                locked_title=locked_title,
                intent_core=intent_core,
                glossary_terms=glossary_terms,
                claim_targets=claim_targets,
                confusion_targets=confusion_targets,
                source_slices=source_slices,
                evidence_items=evidence_items,
                plan=plan,
                docgen_history_brief=docgen_history_brief,
                learner_profile_text=learner_profile_text,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.CHAPTER_EXECUTION_BRIEF,
                digest_mode=digest_mode,
                extra_metadata=extra_metadata,
                docgen_stage="build_chapter_execution_brief",
            ),
            response_model=ChapterExecutionBrief,
        )

    try:
        timeout_s = _chapter_brief_timeout_seconds()
        (response,) = await asyncio.wait_for(
            run_llm_tasks([None], _run_chapter_brief, max_concurrent=1),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError as exc:
        logger.warning("docgen_chapter_brief_timeout", chapter_index=chapter_index, timeout_s=timeout_s)
        raise ChapterExecutionBriefError(f"LLM timed out building chapter brief for chapter {chapter_index}.") from exc
    except Exception as exc:
        logger.warning("docgen_chapter_brief_failed", chapter_index=chapter_index, error=str(exc))
        raise ChapterExecutionBriefError(f"LLM failed to build chapter brief for chapter {chapter_index}.") from exc
    try:
        brief = response if isinstance(response, ChapterExecutionBrief) else ChapterExecutionBrief.model_validate(response)
    except Exception as exc:
        raise ChapterExecutionBriefError(f"LLM returned invalid chapter brief schema for chapter {chapter_index}.") from exc
    brief.chapter_index = chapter_index
    brief.teaching_outline = clean_string_list(brief.teaching_outline, limit=3)
    brief.concept_targets = clean_string_list(brief.concept_targets, limit=2)
    brief.definition_targets = clean_string_list(brief.definition_targets, limit=2)
    brief.formula_targets = clean_string_list(brief.formula_targets, limit=2)
    brief.example_targets = clean_string_list(brief.example_targets, limit=2)
    brief.pitfall_targets = clean_string_list(brief.pitfall_targets, limit=2)
    brief.retrieval_queries = clean_string_list(brief.retrieval_queries, limit=2)
    if not brief.teaching_outline or not brief.retrieval_queries:
        raise ChapterExecutionBriefError(f"LLM returned an incomplete chapter brief for chapter {chapter_index}.")
    if not brief.content_role_targets or not brief.example_coverage_plan:
        raise ChapterExecutionBriefError(f"LLM returned a chapter brief without role targets or examples for chapter {chapter_index}.")
    brief.fallback_used = False
    return brief


__all__ = [
    "ChapterExecutionBriefError",
    "build_chapter_execution_brief",
]
