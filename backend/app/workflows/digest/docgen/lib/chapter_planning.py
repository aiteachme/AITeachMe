"""Chapter task planning for DocGen."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
from app.workflows.digest.docgen.mode_profiles import get_docgen_mode_profile

_MERMAID_STRUCTURE_HINT_TERMS = ("图", "结构", "流程", "关系", "路径", "层次", "机制", "过程")
_STATIC_HTML_FIGURE_HINT_TERMS = (
    "函数",
    "图像",
    "坐标",
    "几何",
    "三角形",
    "四边形",
    "圆",
    "数轴",
    "波形",
    "单位换算",
    "面积",
    "周长",
    "斜率",
)


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


def _suggest_visual_placeholder_requests(
    *,
    title: str,
    required_elements: Sequence[str],
    concept_targets: Sequence[str],
) -> list[dict[str, str]]:
    """Suggest chapter-level asset placeholders before writer generation."""

    visual_terms = " ".join([title, *required_elements, *concept_targets])
    requests: list[dict[str, str]] = []
    if any(marker in visual_terms for marker in _MERMAID_STRUCTURE_HINT_TERMS):
        requests.append({"kind": "mermaid", "description": f"{title} 的结构关系图"})
    if any(marker in visual_terms for marker in _STATIC_HTML_FIGURE_HINT_TERMS):
        requests.append({"kind": "static_html_figure", "description": f"{title} 的静态题图或概念图示"})
    return requests


def _example_coverage_plan(
    *,
    brief: ChapterExecutionBrief,
    required: list[str],
    mode_profile,
) -> list[dict[str, Any]]:
    del required, mode_profile
    plan = clean_example_coverage_plan(brief.example_coverage_plan, limit=16)
    if plan:
        return plan
    raise ValueError("chapter execution brief is missing example_coverage_plan")

def compose_seed_plan_and_backbone_agenda(
    *,
    docgen_context: DocGenContext,
    confirmed_chapters: Sequence[Mapping[str, Any]],
    locked_titles: Sequence[LockedChapterTitle],
    file_summaries: Sequence[FileMaterialSummary],
    source_affinity_by_chapter: Sequence[SourceAffinityByChapter] | None = None,
    high_confidence_evidence_units: Sequence[HighConfidenceEvidenceUnit] | None = None,
    plan_mismatch_warnings: Sequence[str] | None = None,
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
        retrieval_queries = clean_string_list([locked.enhanced_title, *required], limit=2)
        task_seeds.append(
            ChapterGenerationTaskSeed(
                chapter_index=chapter_index,
                confirmed_title=confirmed_title,
                enhanced_title=locked.enhanced_title or confirmed_title,
                chapter_goal=str(chapter.get("objective") or ""),
                mode=docgen_context.digest_mode,
                priority_file_ids=priority_file_ids,
                required_elements=required,
                retrieval_queries=retrieval_queries,
                priority_section_refs=priority_section_refs,
                source_slices=source_slices,
                preferred_sources=preferred_sources,
                target_length=mode_profile.seed_target_length,
                style_rules=list(global_rules),
                allowed_assets=[],
            )
        )
        topics.extend([locked.enhanced_title, *required])
        glossary_candidates.extend(required)
        confusion_candidates.extend([item for item in required if any(marker in item for marker in ("易错", "误区", "混淆", "边界"))])
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
        budget_policy={"chapter_count": len(confirmed_chapters), "max_writer_retries": 1},
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
        min_words, target_words = mode_profile.word_budget(
            chapter_count=chapter_count,
            depth_level=intent_profile.depth_level,
            target_length=str(build_constraints.get("target_length") or ""),
            target_total_words=build_constraints.get("target_total_words"),
        )
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
        placeholder_requests = _suggest_visual_placeholder_requests(
            title=locked.enhanced_title or confirmed_title,
            required_elements=seed.required_elements,
            concept_targets=brief.concept_targets,
        )
        content_role_targets = clean_content_role_targets(brief.content_role_targets, item_limit=10)
        if not content_role_targets:
            raise ValueError(f"chapter execution brief is missing role targets for chapter {chapter_index}")
        example_coverage_plan = _example_coverage_plan(
            brief=brief,
            required=list(seed.required_elements),
            mode_profile=mode_profile,
        )
        task = ChapterGenerationTask(
            chapter_index=chapter_index,
            confirmed_title=confirmed_title,
            enhanced_title=locked.enhanced_title or confirmed_title,
            objective=seed.chapter_goal or str(chapter.get("objective") or ""),
            teaching_outline=clean_string_list(brief.teaching_outline, limit=3),
            content_role_targets=content_role_targets,
            example_coverage_plan=example_coverage_plan,
            content_points=clean_string_list(seed.required_elements),
            concept_targets=clean_string_list([*brief.concept_targets, *seed.required_elements], limit=8),
            definition_targets=clean_string_list(brief.definition_targets, limit=4),
            formula_targets=clean_string_list(brief.formula_targets, limit=4),
            example_targets=clean_string_list(brief.example_targets, limit=4),
            pitfall_targets=clean_string_list(brief.pitfall_targets, limit=4),
            priority_file_ids=priority_file_ids or clean_string_list(chapter.get("source_file_ids", [])),
            priority_section_refs=priority_section_refs or seed.priority_section_refs,
            source_slices=source_slices,
            retrieval_queries=clean_string_list(brief.retrieval_queries or seed.retrieval_queries, limit=2),
            writing_rules=list(global_rules),
            required_elements=list(seed.required_elements),
            forbidden_scope=list(seed.forbidden_scope),
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
            },
            coverage_threshold=max(mode_profile.coverage_threshold, round(0.55 + intent_profile.review_strictness * 0.25, 3)),
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
        budget_policy={"chapter_count": chapter_count, "max_writer_retries": 1},
        chapters=tasks,
        plan_mismatch_warnings=clean_string_list(warnings),
    )


def estimate_quality_from_markdown(markdown: str, *, required_points: Sequence[str], min_word_count: int) -> float:
    if not markdown.strip():
        return 0.0
    normalized = "".join(markdown.split()).casefold()
    hits = sum(1 for item in required_points if str(item).strip() and "".join(str(item).split()).casefold() in normalized)
    coverage = 1.0 if not required_points else hits / max(1, len(required_points))
    length = min(1.0, count_words(markdown) / max(1, min_word_count))
    structure = 1.0 if markdown.count("\n## ") >= 4 else 0.65
    return round((coverage * 0.45) + (length * 0.3) + (structure * 0.25), 4)


__all__ = [
    "assemble_chapter_generation_plan",
    "compose_seed_plan_and_backbone_agenda",
    "estimate_quality_from_markdown",
]
