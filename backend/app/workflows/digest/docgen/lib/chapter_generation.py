"""Chapter generation planning and fallback drafting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.shared.infra.settings import get_settings
from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.digest.common.pedagogy import resolve_effective_chapter_title
from app.workflows.digest.docgen.lib.models import (
    BackboneResearchAgenda,
    ChapterBudgetPolicy,
    ChapterGenerationPlan,
    ChapterGenerationPlanSeed,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    DocGenContext,
    DocGenIntentProfile,
    EnhancedChapterOutline,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    SourceAffinityByChapter,
    clean_string_list,
)


_SYSTEMATIC_FORMAT = [
    "章节导读",
    "学习目标",
    "关键概念与定义",
    "方法、结构与推理路径",
    "例子、例题与迁移",
    "易错点与边界",
    "本章小结",
    "本章摘要",
]
_SPRINT_FORMAT = [
    "这一章先拿下什么",
    "高频考点和速判抓手",
    "核心概念最短路径",
    "典型题型拆解",
    "最容易错在哪",
    "考前回看清单",
    "本章自检",
]


def _chapter_word_budget(*, digest_mode: str, chapter_count: int, intent: DocGenIntentProfile) -> tuple[int, int]:
    normalized_mode = str(digest_mode or "").strip().lower()
    if normalized_mode == "sprint":
        target = 850 if intent.depth_level == "compact" else 1050
        return 520, target
    base = 1500 if intent.depth_level == "deep" else 1250
    return 850, max(1100, base if chapter_count <= 8 else 1200)


def _priority_files_for_chapter(
    *,
    chapter_index: int,
    file_summaries: Sequence[FileMaterialSummary],
) -> tuple[list[int], list[str]]:
    scored = sorted(
        [
            (
                float(summary.chapter_affinity.get(chapter_index, 0.0)),
                summary.source_quality,
                summary.file_id,
                list(summary.high_value_sections),
            )
            for summary in file_summaries
            if summary.file_id > 0
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


def _dedupe_placeholder_requests(requests: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in requests:
        kind = str(item.get("kind") or "").strip().lower()
        description = str(item.get("description") or "").strip()
        if not kind or not description:
            continue
        if kind in {"images", "image"}:
            kind = "image"
        elif kind != "mermaid":
            continue
        key = (kind, description.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"kind": kind, "description": description})
    return deduped


def compose_chapter_generation_plan(
    *,
    docgen_context: DocGenContext,
    confirmed_chapters: Sequence[Mapping[str, Any]],
    enhanced_outlines: Sequence[EnhancedChapterOutline],
    intent_profile: DocGenIntentProfile,
    file_summaries: Sequence[FileMaterialSummary],
    source_affinity_by_chapter: Sequence[SourceAffinityByChapter] | None = None,
    plan_mismatch_warnings: Sequence[str] | None = None,
) -> ChapterGenerationPlan:
    """把 confirmed plan 和准备阶段结果合成章节执行计划。

    这里是 DocGen 内部“任务派发合同”的收口点：只细化用户确认过的
    章节，不改变章节数量和顺序；同时把 intent、文件摘要、章节亲和度、
    资产意图和预算策略合并成每章可执行的 ChapterGenerationTask。
    """

    outline_by_index = {int(outline.chapter_index): outline for outline in enhanced_outlines}
    chapter_count = len(confirmed_chapters)
    normalized_mode = str(docgen_context.digest_mode or "").strip().lower()
    chapter_format = _SPRINT_FORMAT if normalized_mode == "sprint" else _SYSTEMATIC_FORMAT
    global_rules = [
        "严格按用户确认的章节边界写作，不新增、删除或重排章节。",
        "优先使用本地学习资料；外部来源只用于补缺和校准。",
        "例题若非原始资料或可靠来源，不得称为真题，只能称为自测例题或变式练习。",
        "所有术语、公式和推理必须给出可读解释，避免只抛结论。",
    ]
    if normalized_mode == "sprint":
        global_rules.append("冲刺模式要突出题型、速判、易错点和考前复盘。")
    else:
        global_rules.append("系统模式要突出定义、结构、推理、例子和迁移。")

    tasks: list[ChapterGenerationTask] = []
    for index, chapter in enumerate(confirmed_chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        confirmed_title = resolve_effective_chapter_title(chapter, chapter_index=chapter_index)
        outline = outline_by_index.get(chapter_index) or EnhancedChapterOutline(
            chapter_index=chapter_index,
            confirmed_title=confirmed_title,
            enhanced_title=confirmed_title,
            objective=str(chapter.get("objective") or ""),
            content_points=clean_string_list(chapter.get("required_elements", [])),
            retrieval_queries=clean_string_list([confirmed_title, *chapter.get("required_elements", [])]),
            fallback_used=True,
        )
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
        min_words, target_words = _chapter_word_budget(
            digest_mode=docgen_context.digest_mode,
            chapter_count=chapter_count,
            intent=intent_profile,
        )
        required = clean_string_list(chapter.get("required_elements", []))
        placeholder_requests = _dedupe_placeholder_requests(
            [
                *list(outline.media_requests),
            ]
        )
        image_generation_enabled = get_settings().image_generation_enabled

        visual_terms = " ".join([confirmed_title, *required, *outline.content_points])
        if not image_generation_enabled and not any(item["kind"] == "mermaid" for item in placeholder_requests):
            if any(marker in visual_terms for marker in ("图", "结构", "流程", "关系", "路径", "层次", "机制", "过程")):
                placeholder_requests.append(
                    {"kind": "mermaid", "description": f"{confirmed_title} 的结构关系图"}
                )
        elif image_generation_enabled and not any(item["kind"] == "image" for item in placeholder_requests):
            if any(marker in visual_terms for marker in ("图", "结构", "流程", "关系", "场景", "例题")):
                placeholder_requests.append(
                    {"kind": "image", "description": f"{confirmed_title} 的学习配图或例题场景图"}
                )

        task = ChapterGenerationTask(
            chapter_index=chapter_index,
            confirmed_title=confirmed_title,
            enhanced_title=outline.enhanced_title or confirmed_title,
            objective=outline.objective or str(chapter.get("objective") or ""),
            teaching_outline=outline.teaching_outline,
            content_points=clean_string_list([*outline.content_points, *required]),
            concept_targets=clean_string_list([*outline.concept_targets, *required]),
            definition_targets=outline.definition_targets,
            formula_targets=outline.formula_targets,
            example_targets=outline.example_targets,
            pitfall_targets=outline.pitfall_targets,
            priority_file_ids=priority_file_ids or clean_string_list(chapter.get("source_file_ids", [])),
            priority_section_refs=priority_section_refs,
            retrieval_queries=clean_string_list(outline.retrieval_queries),
            writing_rules=[
                *global_rules,
                intent_profile.chapter_style_hints.get(chapter_index, ""),
            ],
            placeholder_requests=placeholder_requests,
            practice_seed_policy=dict(outline.practice_seed_policy),
            coverage_threshold=0.6 if normalized_mode == "sprint" else 0.72,
            evidence_support_threshold=0.48 if normalized_mode == "sprint" else 0.56,
            repetition_tolerance=0.45 if normalized_mode == "sprint" else 0.3,
            patch_tolerance=0.45 if normalized_mode == "sprint" else 0.32,
            min_word_count=min_words,
            target_word_count=target_words,
            budget_policy=ChapterBudgetPolicy(
                max_research_rounds=2 if normalized_mode == "sprint" else 3,
                max_local_queries=3,
                max_web_queries=2 if normalized_mode == "sprint" else 4,
                max_opened_urls=3 if normalized_mode == "sprint" else 5,
                max_context_chars=4200 if normalized_mode == "sprint" else 6200,
                max_writer_retries=1,
            ),
        )
        tasks.append(task)

    return ChapterGenerationPlan(
        subject=docgen_context.subject,
        digest_mode=docgen_context.digest_mode,
        source_policy=docgen_context.source_strategy,
        writing_rules=global_rules,
        chapter_format=chapter_format,
        budget_policy={
            "chapter_count": chapter_count,
            "max_writer_retries": 1,
        },
        chapters=tasks,
        plan_mismatch_warnings=clean_string_list(plan_mismatch_warnings or []),
    )


def build_plan_seed_and_backbone_agenda(
    *,
    generation_plan: ChapterGenerationPlan,
    high_confidence_evidence_units: Sequence[HighConfidenceEvidenceUnit] | None = None,
    file_summaries: Sequence[FileMaterialSummary] | None = None,
) -> tuple[ChapterGenerationPlanSeed, list[ChapterGenerationTaskSeed], BackboneResearchAgenda]:
    """从章节执行计划派生 seed 和全局骨架议程。

    seed 给 `build_document_backbone` 做整本文档建模；ChapterGenerationPlan
    继续给章节 fan-out 使用。这样可以先形成
    稳定的全书语义中心，再把术语、主张和易混点回填到每章任务。
    """

    evidence_units = list(high_confidence_evidence_units or [])
    summaries = list(file_summaries or [])
    task_seeds: list[ChapterGenerationTaskSeed] = []
    for task in generation_plan.chapters:
        preferred_sources = [
            f"local://file/{file_id}"
            for file_id in task.priority_file_ids
        ]
        preferred_sources.extend(
            unit.source_ref
            for unit in evidence_units
            if task.chapter_index in unit.chapter_affinity
        )
        allowed_assets = clean_string_list(
            [str(item.get("kind") or "") for item in task.placeholder_requests if isinstance(item, dict)],
        )
        task_seeds.append(
            ChapterGenerationTaskSeed(
                chapter_index=task.chapter_index,
                confirmed_title=task.confirmed_title,
                enhanced_title=task.enhanced_title,
                chapter_goal=task.objective,
                mode=generation_plan.digest_mode,
                required_elements=task.required_elements,
                forbidden_scope=task.forbidden_scope,
                retrieval_queries=task.retrieval_queries,
                priority_section_refs=task.priority_section_refs,
                preferred_sources=preferred_sources,
                fallback_policy=task.fallback_policy,
                target_length=task.target_word_count,
                style_rules=task.style_rules or task.writing_rules,
                citation_policy=task.citation_policy,
                uncertainty_policy=task.uncertainty_policy,
                allowed_assets=allowed_assets,
            )
        )

    topics = clean_string_list(
        [
            *[task.enhanced_title for task in generation_plan.chapters],
            *[
                item
                for task in generation_plan.chapters
                for item in [*task.concept_targets, *task.required_elements]
            ],
        ],
    )
    glossary_candidates = clean_string_list(
        [
            *[
                item
                for summary in summaries
                for item in [*summary.definitions, *summary.concepts]
            ],
            *[
                item
                for task in generation_plan.chapters
                for item in task.concept_targets
            ],
        ],
    )
    notation_candidates = clean_string_list(
        [
            item
            for summary in summaries
            for item in summary.formulas
        ],
    )
    confusion_candidates = clean_string_list(
        [
            item
            for task in generation_plan.chapters
            for item in task.pitfall_targets
        ],
    )
    agenda = BackboneResearchAgenda(
        topics=topics,
        section_refs=clean_string_list(
            [ref for task in generation_plan.chapters for ref in task.priority_section_refs],
        ),
        evidence_unit_ids=[unit.evidence_id for unit in evidence_units],
        glossary_candidates=glossary_candidates,
        notation_candidates=notation_candidates,
        confusion_candidates=confusion_candidates,
    )
    plan_seed = ChapterGenerationPlanSeed(
        subject=generation_plan.subject,
        digest_mode=generation_plan.digest_mode,
        source_policy=generation_plan.source_policy,
        writing_rules=generation_plan.writing_rules,
        chapter_format=generation_plan.chapter_format,
        budget_policy=generation_plan.budget_policy,
        chapters=task_seeds,
        plan_mismatch_warnings=generation_plan.plan_mismatch_warnings,
    )
    return plan_seed, task_seeds, agenda


def build_fallback_chapter_markdown(
    *,
    task: ChapterGenerationTask,
    digest_mode: str,
    reason: str,
) -> str:
    title = task.enhanced_title or task.confirmed_title or f"第 {task.chapter_index} 章"
    points = task.content_points or task.concept_targets or [task.objective or title]
    if str(digest_mode or "").strip().lower() == "sprint":
        lines = [
            f"# {title}",
            "",
            "## 这章先拿下什么",
            "",
            task.objective or f"先把《{title}》最常考的抓手讲清楚。",
            "",
            "## 高频抓手",
            "",
            *[f"- {item}" for item in points],
            "",
            "## 典型题型怎么拆",
            "",
            "1. 先找题眼，判断它在考哪个概念或条件。",
            "2. 再选方法，确认为什么这条路径能用。",
            "3. 最后回看易错点，避免机械套结论。",
            "",
            "## 本章自检",
            "",
            f"- 不看正文，试着用 60 秒讲清《{title}》的核心判断路径。",
        ]
    else:
        lines = [
            f"# {title}",
            "",
            "## 章节导读",
            "",
            task.objective or f"本章围绕《{title}》建立一条完整的理解主线。",
            "",
            "## 关键概念与定义",
            "",
            *[f"- {item}" for item in points],
            "",
            "## 方法、结构与推理路径",
            "",
            "先明确概念和条件，再说明结论为什么成立，最后用例子把抽象内容落到具体情境。",
            "",
            "## 本章小结",
            "",
            f"- 《{title}》需要回收为一条可复述的知识主线。",
        ]
    lines.extend(["", f"> [!NOTE]", f"> 本章使用降级草稿生成：{reason}"])
    return "\n".join(lines).strip() + "\n"


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
    "build_plan_seed_and_backbone_agenda",
    "build_fallback_chapter_markdown",
    "compose_chapter_generation_plan",
    "estimate_quality_from_markdown",
]
