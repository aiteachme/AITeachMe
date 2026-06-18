"""Chapter-level execution brief generation for DocGen."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

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


def _first_text(mapping: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = str(mapping.get(key) or "").strip()
        if value:
            return value
    return ""


def _source_slice_targets(source_slices: Sequence[Mapping[str, object]]) -> list[str]:
    targets: list[str] = []
    for source_slice in source_slices[:4]:
        if not isinstance(source_slice, Mapping):
            continue
        targets.extend(
            [
                _first_text(source_slice, "section_title", "section_ref", "header_path"),
                _first_text(source_slice, "summary", "excerpt"),
            ]
        )
    return clean_string_list(targets, limit=4)


def _evidence_targets(evidence_items: Sequence[Mapping[str, object]]) -> list[str]:
    targets: list[str] = []
    for item in evidence_items[:4]:
        if not isinstance(item, Mapping):
            continue
        targets.append(_first_text(item, "text", "claim", "source_title"))
    return clean_string_list(targets, limit=3)


def _formula_like_targets(items: Sequence[str]) -> list[str]:
    markers = ("公式", "模型", "定理", "=", "->", "=>", "∈", "∑", "+", "-", "*", "/")
    return [item for item in clean_string_list(items, limit=8) if any(marker in item for marker in markers)][:2]


def build_fallback_chapter_execution_brief(
    *,
    course_name: str,
    chapter: Mapping[str, object],
    locked_title: str,
    glossary_terms: Sequence[str],
    claim_targets: Sequence[str],
    confusion_targets: Sequence[str],
    source_slices: Sequence[Mapping[str, object]] = (),
    evidence_items: Sequence[Mapping[str, object]] = (),
) -> ChapterExecutionBrief:
    """Build a deterministic brief from already-validated planning artifacts."""

    chapter_index = int(chapter.get("chapter_index", 0) or 0) or 1
    title = (
        str(locked_title or "").strip()
        or _first_text(chapter, "resolved_title", "title")
        or f"第 {chapter_index} 章"
    )
    objective = _first_text(chapter, "objective", "chapter_goal")
    required_elements = clean_string_list(chapter.get("required_elements"), limit=6)
    source_targets = _source_slice_targets(source_slices)
    evidence_targets = _evidence_targets(evidence_items)

    concept_targets = clean_string_list(
        [*glossary_terms, *required_elements, title],
        limit=2,
    )
    definition_targets = clean_string_list([*glossary_terms, *concept_targets], limit=2)
    formula_targets = _formula_like_targets([*required_elements, *claim_targets, *source_targets])
    example_targets = clean_string_list([*claim_targets, *required_elements, *source_targets, title], limit=2)
    pitfall_targets = clean_string_list(
        [
            *confusion_targets,
            f"区分 {concept_targets[0]} 的定义、适用条件和常见误用" if concept_targets else "",
        ],
        limit=2,
    )
    principle_targets = clean_string_list([*claim_targets, objective, *evidence_targets], limit=4)
    role_targets = {
        "concept": concept_targets,
        "principle": principle_targets,
        "misconception": pitfall_targets,
        "application_case": example_targets,
    }
    role_targets = {role: targets for role, targets in role_targets.items() if targets}

    main_target = (concept_targets or required_elements or [title])[0]
    secondary_target = (example_targets or principle_targets or [main_target])[0]
    retrieval_queries = clean_string_list(
        [
            f"{course_name} {title}".strip(),
            title,
            main_target,
        ],
        limit=2,
    )
    example_plan_targets = clean_string_list([*example_targets, *concept_targets, *source_targets], limit=3)
    practice_plan_targets = clean_string_list([*concept_targets, *pitfall_targets, *required_elements, title], limit=3)

    return ChapterExecutionBrief(
        chapter_index=chapter_index,
        teaching_outline=[
            f"先明确 {main_target} 的核心定义、边界和本章学习目标。",
            f"再结合资料证据讲清 {secondary_target} 的推导、关系或使用场景。",
            "最后用例题、易错辨析和小测验完成迁移检查。",
        ],
        content_role_targets=role_targets,
        example_coverage_plan=[
            {
                "target": target,
                "purpose": "用本章资料中的例题、案例或任务验证该知识点能被实际使用。",
                "min_examples": 1,
            }
            for target in example_plan_targets
        ],
        chapter_end_practice_plan=[
            {
                "target": target,
                "purpose": "检查学习者是否能独立解释、迁移或辨析该知识点。",
                "min_examples": 1,
            }
            for target in practice_plan_targets
        ],
        concept_targets=concept_targets,
        definition_targets=definition_targets,
        formula_targets=formula_targets,
        example_targets=example_targets,
        pitfall_targets=pitfall_targets,
        retrieval_queries=retrieval_queries or [title],
        fallback_used=True,
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
    "build_fallback_chapter_execution_brief",
]
