"""Chapter task planning for DocGen."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.digest.common.pedagogy import resolve_effective_chapter_title
from app.workflows.digest.docgen.lib.models import (
    BackboneResearchAgenda,
    ChapterExecutionBrief,
    ChapterBudgetPolicy,
    ChapterGenerationPlan,
    ChapterGenerationPlanSeed,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    DocGenContext,
    DocGenIntentProfile,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    LockedChapterTitle,
    SourceAffinityByChapter,
    clean_string_list,
    clean_content_role_targets,
    clean_example_coverage_plan,
)
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile

_SCOPE_PUNCT_RE = re.compile(r"[\s,，、;；:：/／|｜()（）《》“”\"'`]+")
def _priority_files_for_chapter(
    *,
    chapter_index: int,
    file_summaries: Sequence[FileMaterialSummary],
) -> tuple[list[str], list[str]]:
    scored = sorted(
        [
            (
                float(summary.chapter_affinity.get(chapter_index, 0.0)),
                summary.source_quality,
                summary.file_id,
                list(summary.high_value_sections),
            )
            for summary in file_summaries
            if summary.file_id
        ],
        reverse=True,
    )
    file_ids = [file_id for score, _quality, file_id, _sections in scored if score > 0]
    if not file_ids:
        file_ids = [file_id for _score, _quality, file_id, _sections in scored]
    section_refs = [
        section
        for _score, _quality, _file_id, sections in scored
        for section in sections
    ]
    return file_ids, list(dict.fromkeys(section_refs))


def _affinity_for_chapter(
    *,
    chapter_index: int,
    source_affinity_by_chapter: Sequence[SourceAffinityByChapter] | None,
) -> SourceAffinityByChapter | None:
    for item in list(source_affinity_by_chapter or []):
        if int(item.chapter_index or 0) == int(chapter_index):
            return item
    return None


def _locked_titles_by_index(
    locked_titles: Sequence[LockedChapterTitle],
) -> dict[int, LockedChapterTitle]:
    return {int(item.chapter_index): item for item in locked_titles if int(item.chapter_index or 0) > 0}


def _briefs_by_index(
    briefs: Sequence[ChapterExecutionBrief],
) -> dict[int, ChapterExecutionBrief]:
    return {int(item.chapter_index): item for item in briefs if int(item.chapter_index or 0) > 0}


def _example_coverage_plan(
    *,
    brief: ChapterExecutionBrief,
    required: list[str],
    mode_profile,
) -> list[dict[str, Any]]:
    del required, mode_profile
    plan = clean_example_coverage_plan(brief.example_coverage_plan, limit=16)
    return plan


def _scope_text(value: object) -> str:
    return _SCOPE_PUNCT_RE.sub("", str(value or "")).casefold()


def _scope_match(value: str, scopes: Sequence[str], *, min_chars: int = 4) -> bool:
    candidate = _scope_text(value)
    if len(candidate) < 2:
        return False
    for scope in scopes:
        normalized_scope = _scope_text(scope)
        if len(normalized_scope) < min_chars:
            continue
        if normalized_scope in candidate or candidate in normalized_scope:
            return True
    return False


def _chapter_local_scope(
    *,
    title: str,
    objective: str,
    required: Sequence[str],
) -> list[str]:
    return clean_string_list([title, objective, *required], limit=24)


def _chapter_forbidden_scope(
    *,
    current_index: int,
    confirmed_chapters: Sequence[Mapping[str, Any]],
    locked_by_index: Mapping[int, LockedChapterTitle],
) -> list[str]:
    items: list[str] = []
    for index, chapter in enumerate(confirmed_chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        if chapter_index == current_index:
            continue
        locked = locked_by_index.get(chapter_index)
        title = (locked.enhanced_title if locked is not None else "") or resolve_effective_chapter_title(
            chapter,
            chapter_index=chapter_index,
        )
        items.extend([title, str(chapter.get("objective") or "")])
        items.extend(clean_string_list(chapter.get("required_elements", []), limit=8))
    return clean_string_list(items, limit=48)


def _filter_scope_items(
    values: Sequence[str],
    *,
    local_scope: Sequence[str],
    forbidden_scope: Sequence[str],
    limit: int,
) -> list[str]:
    filtered: list[str] = []
    for item in clean_string_list(values, limit=limit * 2):
        if _scope_match(item, forbidden_scope) and not _scope_match(item, local_scope):
            continue
        filtered.append(item)
        if len(filtered) >= limit:
            break
    return filtered


def _filter_content_role_targets(
    value: Mapping[str, Sequence[str]] | dict[str, list[str]],
    *,
    local_scope: Sequence[str],
    forbidden_scope: Sequence[str],
) -> dict[str, list[str]]:
    cleaned = clean_content_role_targets(value, item_limit=10)
    return {
        role: _filter_scope_items(
            list(items),
            local_scope=local_scope,
            forbidden_scope=forbidden_scope,
            limit=10,
        )
        for role, items in cleaned.items()
    }


def compose_seed_plan_and_backbone_agenda(
    *,
    docgen_context: DocGenContext,
    confirmed_chapters: Sequence[Mapping[str, Any]],
    locked_titles: Sequence[LockedChapterTitle],
    file_summaries: Sequence[FileMaterialSummary],
    source_affinity_by_chapter: Sequence[SourceAffinityByChapter] | None = None,
    high_confidence_evidence_units: Sequence[HighConfidenceEvidenceUnit] | None = None,
    plan_mismatch_warnings: Sequence[str] | None = None,
    max_retrieval_queries_per_chapter: int = 2,
) -> tuple[ChapterGenerationPlanSeed, list[ChapterGenerationTaskSeed], BackboneResearchAgenda]:
    locked_by_index = _locked_titles_by_index(locked_titles)
    evidence_units = list(high_confidence_evidence_units or [])
    mode_profile = get_docgen_mode_profile(docgen_context.digest_mode)
    chapter_format = list(mode_profile.chapter_format)
    global_rules = mode_profile.writing_rules

    task_seeds: list[ChapterGenerationTaskSeed] = []
    warnings = clean_string_list(plan_mismatch_warnings or [])
    topics: list[str] = []
    glossary_candidates: list[str] = []
    confusion_candidates: list[str] = []
    section_refs: list[str] = []
    evidence_unit_ids: list[str] = []

    for index, chapter in enumerate(confirmed_chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        confirmed_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
        locked = locked_by_index.get(chapter_index)
        if locked is None:
            raise ValueError(f"missing locked title for chapter {chapter_index}")
        priority_file_ids, priority_section_refs = _priority_files_for_chapter(
            chapter_index=chapter_index,
            file_summaries=file_summaries,
        )
        affinity = _affinity_for_chapter(
            chapter_index=chapter_index,
            source_affinity_by_chapter=source_affinity_by_chapter,
        )
        if affinity is not None:
            priority_file_ids = affinity.file_ids or priority_file_ids
            priority_section_refs = affinity.section_refs or priority_section_refs
        source_slices = list(affinity.source_slices) if affinity is not None else []
        preferred_sources = [f"local://file/{file_id}" for file_id in priority_file_ids]
        preferred_sources.extend(
            unit.source_ref
            for unit in evidence_units
            if chapter_index in unit.chapter_affinity
        )
        required = clean_string_list(chapter.get("required_elements", []))
        forbidden_scope = _chapter_forbidden_scope(
            current_index=chapter_index,
            confirmed_chapters=confirmed_chapters,
            locked_by_index=locked_by_index,
        )
        retrieval_queries = clean_string_list(
            [locked.enhanced_title, *required],
            limit=max(1, int(max_retrieval_queries_per_chapter)),
        )
        task_seeds.append(
            ChapterGenerationTaskSeed(
                chapter_index=chapter_index,
                confirmed_title=confirmed_title,
                enhanced_title=locked.enhanced_title or confirmed_title,
                chapter_goal=str(chapter.get("objective") or ""),
                mode=docgen_context.digest_mode,
                priority_file_ids=priority_file_ids,
                required_elements=required,
                forbidden_scope=forbidden_scope,
                retrieval_queries=retrieval_queries,
                priority_section_refs=priority_section_refs,
                source_slices=source_slices,
                preferred_sources=preferred_sources,
                target_length=mode_profile.seed_target_length,
                style_rules=clean_string_list(
                    [chapter.get("writing_instructions"), *global_rules],
                    limit=16,
                ),
                allowed_assets=[],
            )
        )
        topics.extend([locked.enhanced_title, *required])
        glossary_candidates.extend(required)
        section_refs.extend(priority_section_refs)
        evidence_unit_ids.extend(
            unit.evidence_id
            for unit in evidence_units
            if chapter_index in unit.chapter_affinity
        )
        warnings.extend(locked.plan_mismatch_warnings)

    plan_seed = ChapterGenerationPlanSeed(
        course_name=docgen_context.course_name,
        digest_mode=docgen_context.digest_mode,
        source_policy=docgen_context.source_strategy,
        writing_rules=list(global_rules),
        chapter_format=chapter_format,
        budget_policy={"chapter_count": len(confirmed_chapters), "max_writer_retries": 0},
        chapters=task_seeds,
        plan_mismatch_warnings=clean_string_list(warnings),
    )
    agenda = BackboneResearchAgenda(
        topics=clean_string_list(topics, limit=64),
        section_refs=clean_string_list(section_refs, limit=48),
        evidence_unit_ids=clean_string_list(evidence_unit_ids, limit=48),
        glossary_candidates=clean_string_list(glossary_candidates, limit=48),
        notation_candidates=clean_string_list(
            [item for summary in file_summaries for item in summary.formulas],
            limit=32,
        ),
        confusion_candidates=clean_string_list(confusion_candidates, limit=32),
    )
    return plan_seed, task_seeds, agenda


def assemble_chapter_generation_plan(
    *,
    docgen_context: DocGenContext,
    confirmed_chapters: Sequence[Mapping[str, Any]],
    locked_titles: Sequence[LockedChapterTitle],
    intent_profile: DocGenIntentProfile,
    file_summaries: Sequence[FileMaterialSummary],
    source_affinity_by_chapter: Sequence[SourceAffinityByChapter] | None = None,
    task_seeds: Sequence[ChapterGenerationTaskSeed],
    chapter_execution_briefs: Sequence[ChapterExecutionBrief],
    plan_mismatch_warnings: Sequence[str] | None = None,
) -> ChapterGenerationPlan:
    chapter_count = len(confirmed_chapters)
    locked_by_index = _locked_titles_by_index(locked_titles)
    briefs_by_index = _briefs_by_index(chapter_execution_briefs)
    mode_profile = get_docgen_mode_profile(docgen_context.digest_mode)
    chapter_format = list(mode_profile.chapter_format)
    global_rules = mode_profile.writing_rules

    seed_by_index = {int(seed.chapter_index): seed for seed in task_seeds}
    tasks: list[ChapterGenerationTask] = []
    warnings = clean_string_list(plan_mismatch_warnings or [])
    for index, chapter in enumerate(confirmed_chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        confirmed_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
        locked = locked_by_index.get(chapter_index)
        if locked is None:
            raise ValueError(f"missing locked title for chapter {chapter_index}")
        seed = seed_by_index.get(chapter_index)
        if seed is None:
            raise ValueError(f"missing generation task seed for chapter {chapter_index}")
        brief = briefs_by_index.get(chapter_index)
        if brief is None:
            raise ValueError(f"missing execution brief for chapter {chapter_index}")
        build_constraints = dict(docgen_context.build_constraints or {})
        # Planner's target_length is a document-level granularity hint. Do not
        # turn that product-wide range into a per-chapter writer target unless a
        # concrete total word budget is present.
        explicit_total_words = build_constraints.get("target_total_words")
        min_words, target_words = mode_profile.word_budget(
            chapter_count=chapter_count,
            depth_level=intent_profile.depth_level,
            target_length=str(build_constraints.get("target_length") or "") if explicit_total_words else "",
            target_total_words=explicit_total_words,
        )
        required_element_count = min(8, len(clean_string_list(seed.required_elements)))
        extra_coverage_units = max(0, required_element_count - 4)
        if extra_coverage_units:
            target_cap = 1800 if mode_profile.is_sprint else 2600
            target_words = min(target_cap, target_words + extra_coverage_units * 150)
            min_words = min(target_words, min_words + extra_coverage_units * 100)
        affinity = _affinity_for_chapter(
            chapter_index=chapter_index,
            source_affinity_by_chapter=source_affinity_by_chapter,
        )
        priority_file_ids, priority_section_refs = _priority_files_for_chapter(
            chapter_index=chapter_index,
            file_summaries=file_summaries,
        )
        if affinity is not None:
            priority_file_ids = affinity.file_ids or priority_file_ids
            priority_section_refs = affinity.section_refs or priority_section_refs
            source_slices = list(affinity.source_slices)
        else:
            source_slices = []
        if seed.priority_file_ids:
            priority_file_ids = seed.priority_file_ids
        if seed.source_slices:
            source_slices = list(seed.source_slices)
        content_role_targets = clean_content_role_targets(brief.content_role_targets, item_limit=10)
        local_scope = _chapter_local_scope(
            title=locked.enhanced_title or confirmed_title,
            objective=seed.chapter_goal or str(chapter.get("objective") or ""),
            required=seed.required_elements,
        )
        forbidden_scope = clean_string_list(
            [
                *seed.forbidden_scope,
                *_chapter_forbidden_scope(
                    current_index=chapter_index,
                    confirmed_chapters=confirmed_chapters,
                    locked_by_index=locked_by_index,
                ),
            ],
            limit=48,
        )
        content_role_targets = _filter_content_role_targets(
            content_role_targets,
            local_scope=local_scope,
            forbidden_scope=forbidden_scope,
        )
        # Mermaid structure is a semantic authoring decision.  The Writer prompt
        # already asks the LLM to emit one only when it materially helps; a local
        # keyword rule must not invent a hierarchy between unrelated targets.
        placeholder_requests: list[dict[str, str]] = []
        example_coverage_plan = _example_coverage_plan(
            brief=brief,
            required=list(seed.required_elements),
            mode_profile=mode_profile,
        )
        density_policy = dict(mode_profile.example_density_policy)
        try:
            chapter_end_plan_limit = int(density_policy.get("chapter_end_practice_max_tasks", 4) or 4)
        except (TypeError, ValueError):
            chapter_end_plan_limit = 4
        chapter_end_plan_limit = max(3, min(12, chapter_end_plan_limit))
        chapter_end_practice_plan = clean_example_coverage_plan(
            getattr(brief, "chapter_end_practice_plan", []),
            limit=chapter_end_plan_limit,
        ) or clean_example_coverage_plan(example_coverage_plan[:chapter_end_plan_limit], limit=chapter_end_plan_limit)
        task = ChapterGenerationTask(
            chapter_index=chapter_index,
            confirmed_title=confirmed_title,
            enhanced_title=locked.enhanced_title or confirmed_title,
            objective=seed.chapter_goal or str(chapter.get("objective") or ""),
            teaching_outline=clean_string_list(brief.teaching_outline, limit=3),
            content_role_targets=content_role_targets,
            example_coverage_plan=example_coverage_plan,
            chapter_end_practice_plan=chapter_end_practice_plan,
            content_points=clean_string_list(seed.required_elements),
            concept_targets=_filter_scope_items(
                list(brief.concept_targets),
                local_scope=local_scope,
                forbidden_scope=forbidden_scope,
                limit=8,
            ),
            definition_targets=_filter_scope_items(
                list(brief.definition_targets),
                local_scope=local_scope,
                forbidden_scope=forbidden_scope,
                limit=4,
            ),
            formula_targets=_filter_scope_items(
                list(brief.formula_targets),
                local_scope=local_scope,
                forbidden_scope=forbidden_scope,
                limit=4,
            ),
            example_targets=_filter_scope_items(
                list(brief.example_targets),
                local_scope=local_scope,
                forbidden_scope=forbidden_scope,
                limit=4,
            ),
            pitfall_targets=_filter_scope_items(
                list(brief.pitfall_targets),
                local_scope=local_scope,
                forbidden_scope=forbidden_scope,
                limit=4,
            ),
            priority_file_ids=priority_file_ids or clean_string_list(chapter.get("source_file_ids", [])),
            priority_section_refs=priority_section_refs or seed.priority_section_refs,
            source_slices=source_slices,
            retrieval_queries=_filter_scope_items(
                list(brief.retrieval_queries or seed.retrieval_queries),
                local_scope=local_scope,
                forbidden_scope=forbidden_scope,
                limit=2,
            ),
            writing_rules=clean_string_list(
                [
                    *brief.writing_instructions,
                    chapter.get("writing_instructions"),
                    *global_rules,
                ],
                limit=16,
            ),
            required_elements=list(seed.required_elements),
            forbidden_scope=forbidden_scope,
            preferred_sources=list(seed.preferred_sources),
            fallback_policy=seed.fallback_policy,
            style_rules=list(seed.style_rules or global_rules),
            citation_policy=seed.citation_policy,
            uncertainty_policy=seed.uncertainty_policy,
            allowed_assets=clean_string_list([str(item.get("kind") or "") for item in placeholder_requests if isinstance(item, dict)]),
            placeholder_requests=placeholder_requests,
            practice_seed_policy={
                "style": mode_profile.practice_style,
                "example_ratio": intent_profile.example_ratio,
                "practice_ratio": intent_profile.practice_ratio,
                "policy": intent_profile.example_practice_policy,
                "content_mix_policy": dict(mode_profile.content_mix_policy),
                "example_density_policy": dict(mode_profile.example_density_policy),
                "coverage_policy": list(mode_profile.coverage_policy),
                "example_coverage_plan": example_coverage_plan,
                "chapter_end_practice_plan": chapter_end_practice_plan,
            },
            coverage_threshold=max(
                0.9,
                mode_profile.coverage_threshold,
                round(0.55 + intent_profile.review_strictness * 0.25, 3),
            ),
            evidence_support_threshold=max(
                mode_profile.evidence_support_threshold,
                round(0.42 + intent_profile.evidence_strictness * 0.28, 3),
            ),
            repetition_tolerance=mode_profile.repetition_tolerance,
            patch_tolerance=mode_profile.patch_tolerance,
            min_word_count=min_words,
            target_word_count=target_words,
            budget_policy=ChapterBudgetPolicy(**mode_profile.budget_policy()),
        )
        tasks.append(task)
        warnings.extend(locked.plan_mismatch_warnings)
        warnings.extend(brief.plan_mismatch_warnings)
    return ChapterGenerationPlan(
        course_name=docgen_context.course_name,
        digest_mode=docgen_context.digest_mode,
        source_policy=docgen_context.source_strategy,
        writing_rules=list(global_rules),
        chapter_format=chapter_format,
        budget_policy={"chapter_count": chapter_count, "max_writer_retries": 0},
        chapters=tasks,
        plan_mismatch_warnings=clean_string_list(warnings),
    )


def estimate_quality_from_markdown(markdown: str, *, required_points: Sequence[str], min_word_count: int) -> float:
    del required_points
    if not markdown.strip():
        return 0.0
    length = min(1.0, count_words(markdown) / max(1, min_word_count))
    structure = 1.0 if markdown.count("\n## ") >= 4 else 0.65
    return round((length * 0.55) + (structure * 0.45), 4)


__all__ = [
    "assemble_chapter_generation_plan",
    "compose_seed_plan_and_backbone_agenda",
    "estimate_quality_from_markdown",
]
