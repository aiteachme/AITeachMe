"""Chapter generation planning and fallback drafting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.digest.common.pedagogy import resolve_effective_chapter_title
from app.workflows.digest.docgen.lib.models import (
    ChapterBudgetPolicy,
    ChapterGenerationPlan,
    ChapterGenerationTask,
    DocGenContext,
    DocGenIntentProfile,
    EnhancedChapterOutline,
    FileMaterialSummary,
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
    file_ids = [file_id for score, _quality, file_id, _sections in scored if score > 0][:5]
    if not file_ids:
        file_ids = [file_id for _score, _quality, file_id, _sections in scored[:3]]
    section_refs = [
        section
        for _score, _quality, _file_id, sections in scored[:4]
        for section in sections[:3]
    ]
    return file_ids, list(dict.fromkeys(section_refs))[:10]


def _placeholder_requests_from_confirmed_chapter(chapter: Mapping[str, Any]) -> list[dict[str, str]]:
    media_hints = chapter.get("media_hints")
    if hasattr(media_hints, "model_dump"):
        media_hints = media_hints.model_dump(mode="json")
    media_hints = dict(media_hints or {})
    requests: list[dict[str, str]] = []
    for kind, field_names in {
        "mermaid": ("mermaid",),
        "image": ("images", "image"),
        "interactive": ("interactive", "interactive_html"),
    }.items():
        for field_name in field_names:
            for description in clean_string_list(media_hints.get(field_name), limit=6):
                requests.append({"kind": kind, "description": description})
    return requests


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
        elif kind in {"interactive_html", "interactive"}:
            kind = "interactive"
        elif kind != "mermaid":
            continue
        key = (kind, description.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"kind": kind, "description": description})
    return deduped[:8]


def compose_chapter_generation_plan(
    *,
    docgen_context: DocGenContext,
    confirmed_chapters: Sequence[Mapping[str, Any]],
    enhanced_outlines: Sequence[EnhancedChapterOutline],
    intent_profile: DocGenIntentProfile,
    file_summaries: Sequence[FileMaterialSummary],
    plan_mismatch_warnings: Sequence[str] | None = None,
) -> ChapterGenerationPlan:
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
            content_points=clean_string_list(chapter.get("required_elements", []), limit=10),
            retrieval_queries=clean_string_list([*chapter.get("search_queries", []), confirmed_title], limit=8),
            fallback_used=True,
        )
        priority_file_ids, priority_section_refs = _priority_files_for_chapter(
            chapter_index=chapter_index,
            file_summaries=file_summaries,
        )
        min_words, target_words = _chapter_word_budget(
            digest_mode=docgen_context.digest_mode,
            chapter_count=chapter_count,
            intent=intent_profile,
        )
        required = clean_string_list(chapter.get("required_elements", []), limit=10)
        placeholder_requests = _dedupe_placeholder_requests(
            [
                *list(outline.media_requests),
                *_placeholder_requests_from_confirmed_chapter(chapter),
            ]
        )
        if not any(item["kind"] == "image" for item in placeholder_requests):
            visual_terms = " ".join([confirmed_title, *required, *outline.content_points])
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
            content_points=clean_string_list([*outline.content_points, *required], limit=14),
            concept_targets=clean_string_list([*outline.concept_targets, *required], limit=12),
            definition_targets=outline.definition_targets,
            formula_targets=outline.formula_targets,
            example_targets=outline.example_targets,
            pitfall_targets=outline.pitfall_targets,
            priority_file_ids=priority_file_ids or clean_string_list(chapter.get("source_file_ids", []), limit=8),
            priority_section_refs=priority_section_refs,
            retrieval_queries=clean_string_list([*outline.retrieval_queries, *chapter.get("search_queries", [])], limit=8),
            writing_rules=[
                *global_rules,
                intent_profile.chapter_style_hints.get(chapter_index, ""),
            ],
            placeholder_requests=placeholder_requests,
            practice_seed_policy=dict(outline.practice_seed_policy),
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
        tone=docgen_context.tone,
        source_policy=docgen_context.source_strategy,
        writing_rules=global_rules,
        chapter_format=chapter_format,
        budget_policy={
            "chapter_count": chapter_count,
            "max_writer_retries": 1,
        },
        chapters=tasks,
        plan_mismatch_warnings=clean_string_list(plan_mismatch_warnings or [], limit=16),
    )


def build_fallback_chapter_markdown(
    *,
    task: ChapterGenerationTask,
    digest_mode: str,
    reason: str,
) -> str:
    title = task.enhanced_title or task.confirmed_title or f"第 {task.chapter_index} 章"
    points = task.content_points[:6] or task.concept_targets[:6] or [task.objective or title]
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
    "build_fallback_chapter_markdown",
    "compose_chapter_generation_plan",
    "estimate_quality_from_markdown",
]
