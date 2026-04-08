"""Planner models, fallback builders, and plan normalization helpers."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.shared.infra.config import get_settings
from app.workflows.digest.shared.models import FastTopicHints, SharedInputs, SubjectProfile

DEFAULT_DIGEST_MODE = "systematic"
DEFAULT_TONE = "encouraging"
SPRINT_CHAPTER_TITLES = ("概念破冰", "公式武器库", "真题实战", "防坑指南")
SYSTEMATIC_FIRST_TITLE = "全景导论"
SYSTEMATIC_LAST_TITLE = "总结与延展"
MEDIA_HINT_KEYS = ("images", "mermaid", "interactive")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


class PlannerChapterPlan(BaseModel):
    chapter_index: int
    title: str
    objective: str = ""
    required_elements: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    writing_instructions: str = ""
    media_hints: dict[str, list[str]] = Field(
        default_factory=lambda: {"images": [], "mermaid": [], "interactive": []}
    )


class BuildPlannerDraft(BaseModel):
    subject: str
    user_goal: str
    digest_mode: str = DEFAULT_DIGEST_MODE
    tone: str = DEFAULT_TONE
    chapter_plan: list[PlannerChapterPlan] = Field(default_factory=list)
    research_queries: list[str] = Field(default_factory=list)
    media_plan: dict[str, Any] = Field(default_factory=dict)
    build_constraints: dict[str, Any] = Field(default_factory=dict)
    plan_summary: str = ""


def _minimal_shared_inputs(subject: str) -> SharedInputs:
    return SharedInputs(
        fast_hints=FastTopicHints(),
        subject_profile=SubjectProfile(subject_name=subject, subject_slug=subject),
    )


def _normalize_digest_mode(value: Any) -> str:
    normalized = str(value or DEFAULT_DIGEST_MODE).strip().lower()
    return "sprint" if normalized == "sprint" else DEFAULT_DIGEST_MODE


def _normalize_tone(value: Any) -> str:
    text = _clean_text(value)
    return text or DEFAULT_TONE


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _is_usable_cn_text(value: Any, *, min_length: int = 2) -> bool:
    text = _clean_text(value)
    return len(text) >= min_length and _has_cjk(text)


def _dedupe_strings(items: Iterable[Any], *, limit: int | None = None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if limit is not None and len(cleaned) >= limit:
            break
    return cleaned


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _coerce_chapter_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_coerce_mapping(item) for item in value]


def _normalize_required_elements(value: Any, fallback: list[str]) -> list[str]:
    cleaned = _dedupe_strings(value or [], limit=8)
    if cleaned and any(_has_cjk(item) for item in cleaned):
        return cleaned
    return list(fallback)


def _normalize_search_queries(value: Any, fallback: list[str]) -> list[str]:
    cleaned = _dedupe_strings(value or [], limit=8)
    return cleaned or list(fallback)


def _normalize_media_hints(value: Any, fallback: dict[str, list[str]]) -> dict[str, list[str]]:
    raw = _coerce_mapping(value)
    normalized: dict[str, list[str]] = {}
    for key in MEDIA_HINT_KEYS:
        items = _dedupe_strings(raw.get(key) or [], limit=5)
        normalized[key] = items or list(fallback.get(key, []))
    return normalized


def _normalize_media_plan(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    raw = _coerce_mapping(value)
    merged = dict(fallback)
    merged.update(raw)
    merged["enable_mermaid"] = bool(merged.get("enable_mermaid", fallback.get("enable_mermaid", True)))
    merged["enable_images"] = bool(merged.get("enable_images", fallback.get("enable_images", False)))
    merged["enable_interactive_html"] = bool(
        merged.get("enable_interactive_html", fallback.get("enable_interactive_html", False))
    )
    return merged


def _normalize_build_constraints(value: Any, fallback: dict[str, Any], *, digest_mode: str) -> dict[str, Any]:
    raw = _coerce_mapping(value)
    merged = dict(fallback)
    merged.update(raw)
    merged["include_exercises"] = bool(merged.get("include_exercises", True))
    merged["include_sources"] = bool(merged.get("include_sources", True))
    merged["math_mode"] = bool(merged.get("math_mode", False))
    if digest_mode == "sprint":
        merged["fixed_chapter_count"] = 4
        merged.pop("min_chapters", None)
        merged.pop("max_chapters", None)
        merged.setdefault("target_length", "3000-5000字")
    else:
        merged["min_chapters"] = 6
        merged["max_chapters"] = 10
        merged.pop("fixed_chapter_count", None)
        merged.setdefault("target_length", "10000-15000字")
    return merged


def _collect_topic_hints(shared_inputs: SharedInputs | None, *, limit: int = 8) -> list[str]:
    if shared_inputs is None:
        return []
    raw_topics = [
        *shared_inputs.subject_profile.key_topics,
        *shared_inputs.fast_hints.chapter_candidates,
    ]
    return _dedupe_strings(raw_topics, limit=limit)


def _build_sprint_chapter_specs(
    *,
    subject: str,
    shared_inputs: SharedInputs,
) -> list[tuple[str, str, list[str], list[str], str, dict[str, list[str]]]]:
    topics = _collect_topic_hints(shared_inputs, limit=4)
    focus_topic = topics[0] if topics else (shared_inputs.subject_profile.subject_name or subject)
    return [
        (
            "概念破冰",
            "先用生活化视角把最难啃的概念讲明白，让学生快速建立第一层直觉。",
            ["通俗类比", "核心概念", "知识关系"],
            [
                f"{subject} {focus_topic} 通俗理解",
                f"{subject} {focus_topic} 核心概念 梳理",
            ],
            "必须先用生活例子或考场场景引入，再解释核心概念之间的关系，并加入一个 Mermaid 速记图占位符。",
            {
                "images": [f"{focus_topic} 的直观示意图"],
                "mermaid": [f"{focus_topic} 的概念速记图"],
                "interactive": [],
            },
        ),
        (
            "公式武器库",
            "把最关键的公式、适用条件和大白话翻译整理成冲刺可背的工具箱。",
            ["核心公式", "适用条件", "公式翻译"],
            [
                f"{subject} {focus_topic} 公式 总结",
                f"{subject} {focus_topic} 常用公式 条件",
            ],
            "每个公式后面都要补一句大白话解释，并强调什么时候能用、什么时候最容易用错。",
            {
                "images": [f"{focus_topic} 的公式使用示意图"],
                "mermaid": [f"{focus_topic} 公式之间的关系图"],
                "interactive": [],
            },
        ),
        (
            "真题实战",
            "围绕高频题型拆步骤、讲思路、补变式，帮助学生形成考场操作感。",
            ["典型题型", "步骤推导", "变式提醒"],
            [
                f"{subject} {focus_topic} 典型例题 解析",
                f"{subject} {focus_topic} 真题 解法",
            ],
            "必须给出步骤化拆解，突出题型抓手、关键转折点和一题多变的提醒。",
            {
                "images": [f"{focus_topic} 典型题型的步骤图"],
                "mermaid": [f"{focus_topic} 解题流程图"],
                "interactive": [],
            },
        ),
        (
            "防坑指南",
            "汇总最常见的误区、混淆点和考前检查清单，帮助学生最后兜底。",
            ["易错点", "混淆概念", "考前清单"],
            [
                f"{subject} {focus_topic} 易错点 总结",
                f"{subject} {focus_topic} 常见陷阱 对比",
            ],
            "要明确列出最常见的错法、为什么会错，以及考前一分钟应该回看什么。",
            {
                "images": [f"{focus_topic} 常见错误示意图"],
                "mermaid": [f"{focus_topic} 易错点对照图"],
                "interactive": [],
            },
        ),
    ]


def _build_systematic_middle_titles(topic_hints: list[str], *, target_count: int) -> list[str]:
    fallback_titles = [
        "核心定义与符号",
        "关键结构与公式",
        "推理与证明思路",
        "应用与例题",
        "易混概念与边界条件",
        "方法串联与综合理解",
        "典型场景与扩展问题",
        "知识回看与迁移练习",
    ]
    if topic_hints:
        hinted_titles = [f"{topic}：核心定义与方法" for topic in topic_hints[:target_count]]
        if len(hinted_titles) >= target_count:
            return hinted_titles[:target_count]
        return hinted_titles + fallback_titles[: target_count - len(hinted_titles)]
    return fallback_titles[:target_count]


def _build_systematic_chapter_specs(
    *,
    subject: str,
    shared_inputs: SharedInputs,
    target_count: int | None = None,
) -> list[tuple[str, str, list[str], list[str], str, dict[str, list[str]]]]:
    topic_hints = _collect_topic_hints(shared_inputs, limit=8)
    if target_count is None:
        target_count = math.ceil(max(1, len(topic_hints)) / 1.5) + 2
    target_count = min(10, max(6, target_count))
    middle_titles = _build_systematic_middle_titles(topic_hints, target_count=target_count - 2)
    titles = [SYSTEMATIC_FIRST_TITLE, *middle_titles, SYSTEMATIC_LAST_TITLE]
    overall_topic = "、".join(topic_hints[:4]) if topic_hints else (shared_inputs.subject_profile.subject_name or subject)
    specs: list[tuple[str, str, list[str], list[str], str, dict[str, list[str]]]] = []

    for index, title in enumerate(titles, start=1):
        if index == 1:
            specs.append(
                (
                    SYSTEMATIC_FIRST_TITLE,
                    "先建立整个主题的知识全景、学习顺序和章节关系，再进入细节。",
                    ["知识全景", "学习路径", "概念关系图"],
                    [
                        f"{subject} {overall_topic} 知识框架",
                        f"{subject} {overall_topic} 学习路线",
                    ],
                    "这一章必须是全景导论，先交代整体学习路径，再给出全局脉络图，并说明后续章节分别解决什么问题。",
                    {
                        "images": [f"{overall_topic} 的整体结构示意图"],
                        "mermaid": [f"{overall_topic} 的全景知识脉络图"],
                        "interactive": [],
                    },
                )
            )
            continue
        if index == len(titles):
            specs.append(
                (
                    SYSTEMATIC_LAST_TITLE,
                    "回收整份文档的主线，串起核心知识，并给出进一步深入学习的路径。",
                    ["全局串联", "常见误区", "进阶路径"],
                    [
                        f"{subject} {overall_topic} 总结 复习",
                        f"{subject} {overall_topic} 进阶 学习路径",
                    ],
                    "这一章必须承担总结与延展的职责，回顾全文主线，并给出后续进阶建议。",
                    {
                        "images": [f"{overall_topic} 的进阶学习路线图"],
                        "mermaid": [f"{overall_topic} 的知识回收图"],
                        "interactive": [],
                    },
                )
            )
            continue

        focus_topic = title.split("：", 1)[0].strip() or title
        specs.append(
            (
                title,
                f"围绕“{focus_topic}”建立定义、公式、推理、应用之间的系统理解。",
                ["前置知识", "核心定义", "推理或证明", "应用示例"],
                [
                    f"{subject} {focus_topic} 定义 公式",
                    f"{subject} {focus_topic} 例题 应用",
                ],
                "本章要按“前置知识 -> 动机引入 -> 核心定义与定理 -> 推理与应用 -> 本章要点”的结构展开。",
                {
                    "images": [f"{focus_topic} 的解释性配图"],
                    "mermaid": [f"{focus_topic} 在整体知识中的位置图"],
                    "interactive": [],
                },
            )
        )
    return specs


def _chapter_from_spec(
    index: int,
    spec: tuple[str, str, list[str], list[str], str, dict[str, list[str]]],
) -> PlannerChapterPlan:
    title, objective, required_elements, queries, instructions, media_hints = spec
    return PlannerChapterPlan(
        chapter_index=index,
        title=title,
        objective=objective,
        required_elements=required_elements,
        search_queries=queries,
        writing_instructions=instructions,
        media_hints=media_hints,
    )


def _build_sprint_fallback_plan(
    *,
    subject: str,
    user_goal: str,
    tone: str,
    shared_inputs: SharedInputs,
) -> BuildPlannerDraft:
    settings = get_settings()
    chapter_plan = [
        _chapter_from_spec(index, spec)
        for index, spec in enumerate(
            _build_sprint_chapter_specs(subject=subject, shared_inputs=shared_inputs),
            start=1,
        )
    ]
    research_queries = [query for chapter in chapter_plan for query in chapter.search_queries]
    return BuildPlannerDraft(
        subject=subject,
        user_goal=user_goal,
        digest_mode="sprint",
        tone=tone,
        chapter_plan=chapter_plan,
        research_queries=_dedupe_strings(research_queries, limit=24),
        media_plan={
            "enable_mermaid": settings.enable_mermaid_generation,
            "enable_images": settings.enable_image_generation,
            "enable_interactive_html": False,
        },
        build_constraints={
            "fixed_chapter_count": 4,
            "include_exercises": True,
            "include_sources": True,
            "math_mode": shared_inputs.subject_profile.has_heavy_formulas,
            "target_length": "3000-5000字",
        },
        plan_summary=(
            f"围绕 {subject} 生成一份冲刺型知识文档，固定为 4 章："
            "概念破冰、公式武器库、真题实战、防坑指南。"
        ),
    )


def _build_systematic_fallback_plan(
    *,
    subject: str,
    user_goal: str,
    tone: str,
    shared_inputs: SharedInputs,
    target_count: int | None = None,
) -> BuildPlannerDraft:
    settings = get_settings()
    chapter_plan = [
        _chapter_from_spec(index, spec)
        for index, spec in enumerate(
            _build_systematic_chapter_specs(
                subject=subject,
                shared_inputs=shared_inputs,
                target_count=target_count,
            ),
            start=1,
        )
    ]
    research_queries = [query for chapter in chapter_plan for query in chapter.search_queries]
    return BuildPlannerDraft(
        subject=subject,
        user_goal=user_goal,
        digest_mode="systematic",
        tone=tone,
        chapter_plan=chapter_plan,
        research_queries=_dedupe_strings(research_queries, limit=24),
        media_plan={
            "enable_mermaid": settings.enable_mermaid_generation,
            "enable_images": settings.enable_image_generation,
            "enable_interactive_html": False,
        },
        build_constraints={
            "min_chapters": 6,
            "max_chapters": 10,
            "include_exercises": True,
            "include_sources": True,
            "math_mode": shared_inputs.subject_profile.has_heavy_formulas,
            "target_length": "10000-15000字",
        },
        plan_summary=(
            f"围绕 {subject} 生成一份系统型知识文档，首章为全景导论，"
            "末章为总结与延展，中间章节按主题逐层展开。"
        ),
    )


def build_fallback_plan(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    tone: str,
    shared_inputs: SharedInputs,
    target_count: int | None = None,
) -> BuildPlannerDraft:
    normalized_mode = _normalize_digest_mode(digest_mode)
    normalized_tone = _normalize_tone(tone)
    if normalized_mode == "sprint":
        return _build_sprint_fallback_plan(
            subject=subject,
            user_goal=user_goal,
            tone=normalized_tone,
            shared_inputs=shared_inputs,
        )
    return _build_systematic_fallback_plan(
        subject=subject,
        user_goal=user_goal,
        tone=normalized_tone,
        shared_inputs=shared_inputs,
        target_count=target_count,
    )


def _merge_raw_candidates(current: Any, previous: Any) -> dict[str, Any]:
    merged = _coerce_mapping(previous)
    merged.update(_coerce_mapping(current))
    return merged


def _merge_chapter(
    *,
    current: Any,
    previous: Any,
    fallback: PlannerChapterPlan,
    forced_title: str | None = None,
) -> PlannerChapterPlan:
    raw = _merge_raw_candidates(current, previous)
    title = forced_title or (_clean_text(raw.get("title")) if _is_usable_cn_text(raw.get("title")) else fallback.title)
    objective = _clean_text(raw.get("objective")) if _is_usable_cn_text(raw.get("objective"), min_length=6) else fallback.objective
    writing_instructions = (
        _clean_text(raw.get("writing_instructions"))
        if _is_usable_cn_text(raw.get("writing_instructions"), min_length=8)
        else fallback.writing_instructions
    )
    return PlannerChapterPlan(
        chapter_index=fallback.chapter_index,
        title=title,
        objective=objective,
        required_elements=_normalize_required_elements(raw.get("required_elements"), fallback.required_elements),
        search_queries=_normalize_search_queries(raw.get("search_queries"), fallback.search_queries),
        writing_instructions=writing_instructions,
        media_hints=_normalize_media_hints(raw.get("media_hints"), fallback.media_hints),
    )


def _normalize_sprint_chapters(
    *,
    current_chapters: list[dict[str, Any]],
    previous_chapters: list[dict[str, Any]],
    fallback_plan: BuildPlannerDraft,
) -> list[PlannerChapterPlan]:
    normalized: list[PlannerChapterPlan] = []
    for index, fallback in enumerate(fallback_plan.chapter_plan):
        current = current_chapters[index] if index < len(current_chapters) else {}
        previous = previous_chapters[index] if index < len(previous_chapters) else {}
        normalized.append(
            _merge_chapter(
                current=current,
                previous=previous,
                fallback=fallback,
                forced_title=SPRINT_CHAPTER_TITLES[index],
            )
        )
    return normalized


def _normalize_middle_title(raw_title: Any, fallback_title: str) -> str:
    text = _clean_text(raw_title)
    if _is_usable_cn_text(text) and text not in {SYSTEMATIC_FIRST_TITLE, SYSTEMATIC_LAST_TITLE}:
        return text
    return fallback_title


def _normalize_systematic_chapters(
    *,
    subject: str,
    user_goal: str,
    tone: str,
    shared_inputs: SharedInputs,
    current_chapters: list[dict[str, Any]],
    previous_chapters: list[dict[str, Any]],
) -> list[PlannerChapterPlan]:
    raw_count = len(current_chapters) or len(previous_chapters) or 0
    target_count = min(10, max(6, raw_count or 6))
    fallback_plan = build_fallback_plan(
        subject=subject,
        user_goal=user_goal,
        digest_mode="systematic",
        tone=tone,
        shared_inputs=shared_inputs,
        target_count=target_count,
    )
    normalized: list[PlannerChapterPlan] = []
    last_index = target_count - 1
    middle_current = current_chapters[1:-1] if len(current_chapters) >= 2 else []
    middle_previous = previous_chapters[1:-1] if len(previous_chapters) >= 2 else []

    normalized.append(
        _merge_chapter(
            current=current_chapters[0] if current_chapters else {},
            previous=previous_chapters[0] if previous_chapters else {},
            fallback=fallback_plan.chapter_plan[0],
            forced_title=SYSTEMATIC_FIRST_TITLE,
        )
    )

    for offset, fallback in enumerate(fallback_plan.chapter_plan[1:-1], start=0):
        current = middle_current[offset] if offset < len(middle_current) else {}
        previous = middle_previous[offset] if offset < len(middle_previous) else {}
        merged_raw = _merge_raw_candidates(current, previous)
        forced_title = _normalize_middle_title(merged_raw.get("title"), fallback.title)
        normalized.append(
            _merge_chapter(
                current=current,
                previous=previous,
                fallback=fallback,
                forced_title=forced_title,
            )
        )

    normalized.append(
        _merge_chapter(
            current=current_chapters[-1] if len(current_chapters) >= 2 else {},
            previous=previous_chapters[-1] if len(previous_chapters) >= 2 else {},
            fallback=fallback_plan.chapter_plan[last_index],
            forced_title=SYSTEMATIC_LAST_TITLE,
        )
    )
    return normalized


def _normalize_plan_summary(value: Any, fallback: str, *, digest_mode: str) -> str:
    text = _clean_text(value)
    if not _is_usable_cn_text(text, min_length=10):
        return fallback
    required_keywords = ("冲刺", "速记", "抓分", "真题") if digest_mode == "sprint" else ("系统", "全景", "逐层", "延展")
    if not any(keyword in text for keyword in required_keywords):
        return fallback
    return text


def normalize_planner_draft(
    draft: BuildPlannerDraft | Mapping[str, Any] | None,
    *,
    subject: str,
    user_goal: str,
    requested_digest_mode: str,
    requested_tone: str,
    shared_inputs: SharedInputs | None = None,
    latest_plan: BuildPlannerDraft | Mapping[str, Any] | None = None,
) -> BuildPlannerDraft:
    shared = shared_inputs or _minimal_shared_inputs(subject)
    current_raw = _coerce_mapping(draft)
    previous_raw = _coerce_mapping(latest_plan)
    digest_mode = _normalize_digest_mode(
        requested_digest_mode or current_raw.get("digest_mode") or previous_raw.get("digest_mode")
    )
    tone = _normalize_tone(requested_tone or current_raw.get("tone") or previous_raw.get("tone"))

    if digest_mode == "sprint":
        fallback_plan = build_fallback_plan(
            subject=subject,
            user_goal=user_goal,
            digest_mode=digest_mode,
            tone=tone,
            shared_inputs=shared,
        )
        chapter_plan = _normalize_sprint_chapters(
            current_chapters=_coerce_chapter_mappings(current_raw.get("chapter_plan")),
            previous_chapters=_coerce_chapter_mappings(previous_raw.get("chapter_plan")),
            fallback_plan=fallback_plan,
        )
    else:
        fallback_plan = build_fallback_plan(
            subject=subject,
            user_goal=user_goal,
            digest_mode=digest_mode,
            tone=tone,
            shared_inputs=shared,
        )
        chapter_plan = _normalize_systematic_chapters(
            subject=subject,
            user_goal=user_goal,
            tone=tone,
            shared_inputs=shared,
            current_chapters=_coerce_chapter_mappings(current_raw.get("chapter_plan")),
            previous_chapters=_coerce_chapter_mappings(previous_raw.get("chapter_plan")),
        )
        fallback_plan = fallback_plan.model_copy(update={"chapter_plan": chapter_plan})

    chapter_queries = [query for chapter in chapter_plan for query in chapter.search_queries]
    research_queries = _dedupe_strings(
        [
            *list(current_raw.get("research_queries") or []),
            *list(previous_raw.get("research_queries") or []),
            *chapter_queries,
        ],
        limit=24,
    )
    return BuildPlannerDraft(
        subject=subject,
        user_goal=user_goal,
        digest_mode=digest_mode,
        tone=tone,
        chapter_plan=chapter_plan,
        research_queries=research_queries or list(fallback_plan.research_queries),
        media_plan=_normalize_media_plan(
            current_raw.get("media_plan") or previous_raw.get("media_plan"),
            fallback_plan.media_plan,
        ),
        build_constraints=_normalize_build_constraints(
            current_raw.get("build_constraints") or previous_raw.get("build_constraints"),
            fallback_plan.build_constraints,
            digest_mode=digest_mode,
        ),
        plan_summary=_normalize_plan_summary(
            current_raw.get("plan_summary") or previous_raw.get("plan_summary"),
            fallback_plan.plan_summary,
            digest_mode=digest_mode,
        ),
    )


def normalize_planner_payload(
    payload: BuildPlannerDraft | Mapping[str, Any] | None,
    *,
    subject: str,
    user_goal: str,
    requested_digest_mode: str,
    requested_tone: str,
    shared_inputs: SharedInputs | None = None,
    latest_plan: BuildPlannerDraft | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_planner_draft(
        payload,
        subject=subject,
        user_goal=user_goal,
        requested_digest_mode=requested_digest_mode,
        requested_tone=requested_tone,
        shared_inputs=shared_inputs,
        latest_plan=latest_plan,
    ).model_dump(mode="json")


__all__ = [
    "BuildPlannerDraft",
    "PlannerChapterPlan",
    "build_fallback_plan",
    "normalize_planner_draft",
    "normalize_planner_payload",
]
