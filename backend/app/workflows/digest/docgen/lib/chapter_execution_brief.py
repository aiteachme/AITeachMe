"""Chapter-level execution brief generation for DocGen."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.workflows.digest.docgen.lib.defaults import DEFAULT_DOCGEN_CHAPTER_BRIEF_PARALLELISM
from app.workflows.digest.docgen.lib.models import ChapterExecutionBrief, clean_string_list, clean_text
from app.workflows.digest.docgen.prompts import build_chapter_execution_brief_messages

logger = structlog.get_logger(__name__)

_CHAPTER_BRIEF_SEMAPHORE: asyncio.Semaphore | None = None


def get_chapter_brief_semaphore() -> asyncio.Semaphore:
    global _CHAPTER_BRIEF_SEMAPHORE
    if _CHAPTER_BRIEF_SEMAPHORE is None:
        _CHAPTER_BRIEF_SEMAPHORE = asyncio.Semaphore(max(1, int(DEFAULT_DOCGEN_CHAPTER_BRIEF_PARALLELISM)))
    return _CHAPTER_BRIEF_SEMAPHORE


def fallback_chapter_execution_brief(
    chapter: Mapping[str, object],
    *,
    digest_mode: str,
) -> ChapterExecutionBrief:
    chapter_index = int(chapter.get("chapter_index", 0) or 0) or 1
    required = clean_string_list(chapter.get("required_elements", []), limit=4)
    normalized_mode = str(digest_mode or "").strip().lower()
    if normalized_mode == "sprint":
        teaching_outline = ["抓本章最重要的考点", "用典型题型带理解", "最后回看易错点"]
    else:
        teaching_outline = ["先讲清定义和主线", "再讲结构与推理", "最后用例子和边界收口"]
    return ChapterExecutionBrief(
        chapter_index=chapter_index,
        teaching_outline=teaching_outline[:3],
        concept_targets=required[:2],
        definition_targets=required[:2],
        formula_targets=[item for item in required if any(marker in item for marker in ("公式", "定理", "性质"))][:2],
        example_targets=required[:2],
        pitfall_targets=["易错点", "边界条件"][:2],
        retrieval_queries=clean_string_list(
            [
                clean_text(chapter.get("title") or chapter.get("resolved_title")),
                *required[:1],
            ],
            limit=2,
        ),
        fallback_used=True,
    )


async def build_chapter_execution_brief(
    *,
    subject: str,
    digest_mode: str,
    chapter: Mapping[str, object],
    locked_title: str,
    intent_core: Mapping[str, object],
    glossary_terms: Sequence[str],
    claim_targets: Sequence[str],
    confusion_targets: Sequence[str],
    extra_metadata: Mapping[str, object] | None = None,
) -> ChapterExecutionBrief:
    fallback = fallback_chapter_execution_brief(chapter, digest_mode=digest_mode)
    try:
        async with get_chapter_brief_semaphore():
            response = await acompletion_with_fallback(
                build_chapter_execution_brief_messages(
                    subject=subject,
                    digest_mode=digest_mode,
                    chapter=chapter,
                    locked_title=locked_title,
                    intent_core=intent_core,
                    glossary_terms=glossary_terms,
                    claim_targets=claim_targets,
                    confusion_targets=confusion_targets,
                ),
                task_type=TaskType.REASONING,
                model="reason",
                response_model=ChapterExecutionBrief,
                temperature=0.1,
                max_tokens=420,
                extra_metadata={"docgen_stage": "build_chapter_execution_brief", **dict(extra_metadata or {})},
            )
    except Exception as exc:
        logger.warning("docgen_chapter_brief_failed", chapter_index=fallback.chapter_index, error=str(exc))
        return fallback
    try:
        brief = response if isinstance(response, ChapterExecutionBrief) else ChapterExecutionBrief.model_validate(response)
    except Exception:
        return fallback
    brief.chapter_index = fallback.chapter_index
    brief.teaching_outline = clean_string_list(brief.teaching_outline, limit=3)
    brief.concept_targets = clean_string_list(brief.concept_targets, limit=2)
    brief.definition_targets = clean_string_list(brief.definition_targets, limit=2)
    brief.formula_targets = clean_string_list(brief.formula_targets, limit=2)
    brief.example_targets = clean_string_list(brief.example_targets, limit=2)
    brief.pitfall_targets = clean_string_list(brief.pitfall_targets, limit=2)
    brief.retrieval_queries = clean_string_list(brief.retrieval_queries, limit=2)
    brief.fallback_used = False
    if not brief.teaching_outline:
        brief.teaching_outline = fallback.teaching_outline
    if not brief.retrieval_queries:
        brief.retrieval_queries = fallback.retrieval_queries
    return brief


__all__ = ["build_chapter_execution_brief", "fallback_chapter_execution_brief"]
