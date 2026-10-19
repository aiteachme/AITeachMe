"""Chapter-level execution brief generation for DocGen."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import structlog

from app.shared.infra.env_support import get_env_bounded_float
from app.shared.infra.exceptions import LLMTimeoutError
from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.settings import get_settings
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterExecutionBriefForGeneration,
    clean_string_list,
)
from app.workflows.digest.docgen.lib.quantity_contracts import (
    chapter_end_question_contract_issues,
    infer_explicit_chapter_end_question_contracts,
)
from app.workflows.digest.docgen.prompts.chapter_execution_brief import build_chapter_execution_brief_messages

logger = structlog.get_logger(__name__)


class ChapterExecutionBriefError(RuntimeError):
    """Raised when the LLM cannot produce a usable chapter execution brief."""


def _chapter_brief_timeout_seconds() -> float:
    return get_env_bounded_float(
        "DOCGEN_CHAPTER_EXECUTION_BRIEF_TIMEOUT_S",
        180.0,
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
    user_prompt: str = "",
    plan: str = "",
    docgen_history_brief: str = "",
    learner_profile_text: str = "",
    extra_metadata: Mapping[str, object] | None = None,
) -> ChapterExecutionBrief:
    chapter_index = int(chapter.get("chapter_index", 0) or 0) or 1
    timeout_s = _chapter_brief_timeout_seconds()
    retrieval_query_limit = get_settings().docgen.max_retrieval_queries_per_chapter

    completion_kwargs = docgen_completion_kwargs_with_metadata(
        DocGenModelStep.CHAPTER_EXECUTION_BRIEF,
        digest_mode=digest_mode,
        extra_metadata=extra_metadata,
        docgen_stage="build_chapter_execution_brief",
    )
    completion_kwargs["overall_timeout_s"] = timeout_s
    try:
        response = await acompletion_with_fallback(
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
                user_prompt=user_prompt,
                plan=plan,
                docgen_history_brief=docgen_history_brief,
                learner_profile_text=learner_profile_text,
                max_retrieval_queries_per_chapter=retrieval_query_limit,
            ),
            **completion_kwargs,
            response_model=ChapterExecutionBriefForGeneration,
        )
    except LLMTimeoutError as exc:
        logger.warning("docgen_chapter_brief_timeout", chapter_index=chapter_index, timeout_s=timeout_s)
        raise ChapterExecutionBriefError(f"LLM timed out building chapter brief for chapter {chapter_index}.") from exc
    except Exception as exc:
        logger.warning("docgen_chapter_brief_failed", chapter_index=chapter_index, error=str(exc))
        raise ChapterExecutionBriefError(f"LLM failed to build chapter brief for chapter {chapter_index}.") from exc
    try:
        brief = ChapterExecutionBriefForGeneration.model_validate(
            response.model_dump(mode="json") if isinstance(response, ChapterExecutionBrief) else response,
        )
    except Exception as exc:
        raise ChapterExecutionBriefError(f"LLM returned invalid chapter brief schema for chapter {chapter_index}.") from exc
    chapter_scoped_sources = tuple(clean_string_list([
        *clean_string_list(chapter.get("style_rules")),
        *clean_string_list(chapter.get("writing_instructions")),
    ]))
    # ``ChapterGenerationTaskSeed`` carries the planner handoff as
    # ``style_rules``.  Use it when it contains an explicit quantity contract;
    # otherwise fall back to the original request, without scanning the full
    # course plan where another chapter may have a different allocation.
    if infer_explicit_chapter_end_question_contracts(chapter_scoped_sources):
        quantity_sources = chapter_scoped_sources
    else:
        user_source = str(user_prompt or "").strip()
        plan_source = str(plan or "").strip()
        plan_contracts = infer_explicit_chapter_end_question_contracts((plan_source,))
        user_contracts = infer_explicit_chapter_end_question_contracts((user_source,))
        # A single confirmed-plan contract is the strongest source.  If the
        # plan contains several chapter allocations and no scoped handoff was
        # available, do not apply an unscoped contract to every chapter.
        if len(plan_contracts) == 1:
            quantity_sources = (plan_source,)
        elif len(user_contracts) == 1:
            quantity_sources = (user_source,)
        else:
            quantity_sources = ()
    quantity_issues = chapter_end_question_contract_issues(
        quantity_constraints=brief.quantity_constraints,
        chapter_end_practice_plan=brief.chapter_end_practice_plan,
        sources=quantity_sources,
    )
    if quantity_issues:
        raise ChapterExecutionBriefError(
            f"LLM chapter brief conflicts with the confirmed chapter-end quantity contract for chapter "
            f"{chapter_index}: {'; '.join(quantity_issues)}"
        )
    brief.chapter_index = chapter_index
    brief.teaching_outline = clean_string_list(brief.teaching_outline, limit=3)
    brief.concept_targets = clean_string_list(brief.concept_targets, limit=2)
    brief.definition_targets = clean_string_list(brief.definition_targets, limit=2)
    brief.formula_targets = clean_string_list(brief.formula_targets, limit=2)
    brief.example_targets = clean_string_list(brief.example_targets, limit=2)
    brief.pitfall_targets = clean_string_list(brief.pitfall_targets, limit=2)
    brief.retrieval_queries = clean_string_list(
        brief.retrieval_queries,
        limit=retrieval_query_limit,
    )
    if not brief.teaching_outline:
        raise ChapterExecutionBriefError(f"LLM returned an incomplete chapter brief for chapter {chapter_index}.")
    if not brief.content_role_targets or (
        not brief.example_coverage_plan and brief.quantity_constraints.worked_example_count != 0
    ):
        raise ChapterExecutionBriefError(f"LLM returned a chapter brief without role targets or examples for chapter {chapter_index}.")
    brief.fallback_used = False
    return brief


__all__ = [
    "ChapterExecutionBriefError",
    "build_chapter_execution_brief",
]
