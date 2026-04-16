"""Planner models, fallback builders, and plan normalization helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.shared.infra.settings import get_settings
from app.workflows.digest.common.pedagogy import (
    clean_generated_chapter_title,
    is_usable_resolved_chapter_title,
)
from app.workflows.digest.common.runtime_config import (
    get_planner_mode_runtime_config,
    get_teaching_runtime_config,
)
from app.workflows.digest.common.models import FastTopicHints, SharedInputs, SubjectProfile

MEDIA_HINT_KEYS = ("images", "mermaid", "interactive")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_SUBJECT_SLUG_RE = re.compile(r"^subj_[a-z0-9]+$", re.IGNORECASE)
_SUBJECT_SLUG_INLINE_RE = re.compile(r"\bsubj_[a-z0-9]+\b", re.IGNORECASE)
_TOPIC_SPLIT_RE = re.compile(r"[，。；：,.!?！？/\n]")
_GOAL_PREFIX_RE = re.compile(
    r"^(?:请|请你|帮我|麻烦你|能不能|可以|想让你)?(?:再)?(?:详细)?(?:系统)?(?:完整)?"
    r"(?:帮我)?(?:整理|梳理|总结|讲解|解释|复习|学习|掌握|冲刺|备考|准备|构建|生成|做|写)"
    r"(?:一份|一下|下)?",
)
_GENERIC_TOPIC_MARKERS = (
    "相关知识",
    "知识点",
    "知识文档",
    "知识体系",
    "学习资料",
    "学习路径",
    "课程内容",
    "课程讲义",
    "系统课",
    "冲刺课",
    "复习资料",
    "整理一下",
    "帮我整理",
    "帮我梳理",
    "总结一下",
)


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
    digest_mode: str = "systematic"
    tone: str = "encouraging"
    selected_skillpacks: list[str] = Field(default_factory=list)
    chapter_plan: list[PlannerChapterPlan] = Field(default_factory=list)
    research_queries: list[str] = Field(default_factory=list)
    media_plan: dict[str, Any] = Field(default_factory=dict)
    build_constraints: dict[str, Any] = Field(default_factory=dict)
    plan_summary: str = ""


class ChapterAngleSpec(BaseModel):
    label: str
    required_elements: list[str] = Field(default_factory=list)
    query_suffixes: list[str] = Field(default_factory=list)
    writing_instruction: str = ""
    objective_template: str = ""


SPRINT_ANGLE_SPECS = [
    ChapterAngleSpec(
        label="核心概念",
        required_elements=["核心概念", "高频考点", "直觉理解"],
        query_suffixes=["核心概念", "通俗理解", "考点梳理"],
        writing_instruction="优先解释最少但最关键的概念，用大白话说明它为什么重要，并点明最常见的考法。",
        objective_template="围绕“{topic}”快速抓住核心概念与考点，先建立能直接拿来应试的理解抓手。",
    ),
    ChapterAngleSpec(
        label="公式方法",
        required_elements=["核心公式", "使用条件", "方法判断"],
        query_suffixes=["公式总结", "方法技巧", "使用条件"],
        writing_instruction="突出公式、方法和使用条件，每个要点都补一条快速判断规则，避免死记硬背。",
        objective_template="围绕“{topic}”整理最常用的公式与方法，帮助学生快速判断什么时候该用什么。",
    ),
    ChapterAngleSpec(
        label="题型突破",
        required_elements=["典型题型", "步骤拆解", "变式提醒"],
        query_suffixes=["典型题型", "例题解析", "真题变式"],
        writing_instruction="按题型展开，明确题眼、解题步骤和变式方向，让学生看到题就能找到入口。",
        objective_template="围绕“{topic}”拆解高频题型与解题路径，把会做一道题扩展成会做一类题。",
    ),
    ChapterAngleSpec(
        label="易错辨析",
        required_elements=["易错点", "混淆概念", "失分原因"],
        query_suffixes=["易错点总结", "常见陷阱", "对比辨析"],
        writing_instruction="集中讲清最容易混淆和失分的地方，明确为什么会错、如何快速自查。",
        objective_template="围绕“{topic}”集中处理最容易失分的误区，避免学生在考场上踩重复的坑。",
    ),
    ChapterAngleSpec(
        label="综合迁移",
        required_elements=["综合变式", "跨题型迁移", "得分策略"],
        query_suffixes=["综合变式", "迁移应用", "得分技巧"],
        writing_instruction="强调同一知识点在不同题型中的变形方式，补充综合场景下的得分策略。",
        objective_template="围绕“{topic}”补足综合变式和迁移能力，避免学生只会单一路径的套路题。",
    ),
    ChapterAngleSpec(
        label="考前速查",
        required_elements=["速查表", "最后回看", "记忆抓手"],
        query_suffixes=["速查表", "考前回看", "记忆口诀"],
        writing_instruction="压缩表达，形成适合最后回看的速查清单，确保一分钟能复盘关键抓手。",
        objective_template="围绕“{topic}”沉淀一页可快速回看的抓手，让学生在考前能高效完成最后复盘。",
    ),
]

SYSTEMATIC_ANGLE_SPECS = [
    ChapterAngleSpec(
        label="主题导入",
        required_elements=["学习目标", "前置关系", "核心问题"],
        query_suffixes=["学习路径", "知识框架", "前置知识"],
        writing_instruction="先交代这一章解决什么问题、与整套内容如何衔接，再进入细节展开。",
        objective_template="围绕“{topic}”建立学习入口，让学生先知道为什么学、先学什么、后学什么。",
    ),
    ChapterAngleSpec(
        label="概念定义",
        required_elements=["核心定义", "关键概念", "符号说明"],
        query_suffixes=["定义", "概念梳理", "符号说明"],
        writing_instruction="从概念、定义、符号和最小例子出发，搭好本章的理解底座。",
        objective_template="围绕“{topic}”建立准确的概念与定义理解，打牢后续推理和应用的基础。",
    ),
    ChapterAngleSpec(
        label="结构公式",
        required_elements=["关键结构", "核心公式", "成立条件"],
        query_suffixes=["关键结构", "核心公式", "成立条件"],
        writing_instruction="讲清结构、公式和它们的成立边界，不要只罗列结论，要补上使用前提。",
        objective_template="围绕“{topic}”梳理关键结构与公式，帮助学生建立可推演、可调用的知识骨架。",
    ),
    ChapterAngleSpec(
        label="方法推理",
        required_elements=["推理过程", "方法步骤", "判断依据"],
        query_suffixes=["推理思路", "方法步骤", "证明思路"],
        writing_instruction="强调方法链路、推理过程和判断依据，让学生知道为什么这样做而不是只记结果。",
        objective_template="围绕“{topic}”建立从原理到方法的推理链，形成更完整的系统理解。",
    ),
    ChapterAngleSpec(
        label="例题应用",
        required_elements=["典型例题", "应用场景", "变式扩展"],
        query_suffixes=["例题解析", "应用场景", "变式拓展"],
        writing_instruction="通过例题与应用场景把抽象知识落地，突出从概念到解题的转化过程。",
        objective_template="围绕“{topic}”把知识落到典型例题和应用场景中，提升理解到运用的转化能力。",
    ),
    ChapterAngleSpec(
        label="边界辨析",
        required_elements=["易混点", "边界条件", "反例提醒"],
        query_suffixes=["易混概念", "边界条件", "反例辨析"],
        writing_instruction="专门处理容易混淆的边界和反例，避免学生形成看似顺畅但不稳的理解。",
        objective_template="围绕“{topic}”处理最容易混淆的边界条件和反例，补齐系统学习中最容易漏掉的薄弱点。",
    ),
    ChapterAngleSpec(
        label="综合迁移",
        required_elements=["综合问题", "跨主题联系", "迁移能力"],
        query_suffixes=["综合问题", "知识联系", "迁移应用"],
        writing_instruction="把多个主题串起来，说明它们如何在综合问题中协同出现并互相支撑。",
        objective_template="围绕“{topic}”搭建跨主题联系，帮助学生把局部知识组织成可迁移的整体能力。",
    ),
    ChapterAngleSpec(
        label="总结延伸",
        required_elements=["本章回顾", "复习建议", "进阶方向"],
        query_suffixes=["总结回顾", "复习建议", "进阶学习"],
        writing_instruction="收束这一章的主线，指出后续延伸方向和推荐的复习顺序。",
        objective_template="围绕“{topic}”完成回收与延伸，帮助学生把本章内容沉淀成稳定的长期结构。",
    ),
]

SPRINT_TITLE_SUFFIXES: dict[str, str] = {
    "核心概念": "核心概念与高频考点",
    "公式方法": "公式与速判技巧",
    "题型突破": "高频题型突破",
    "易错辨析": "易错点辨析",
    "综合迁移": "综合变式与迁移",
    "考前速查": "考前速查清单",
}

SYSTEMATIC_TITLE_SUFFIXES: dict[str, str] = {
    "主题导入": "学习地图与主线",
    "概念定义": "核心概念与定义",
    "结构公式": "结构框架与关键公式",
    "方法推理": "方法推理与证明思路",
    "例题应用": "典型例题与应用",
    "边界辨析": "边界条件与易混辨析",
    "综合迁移": "跨主题综合迁移",
    "总结延伸": "章节总结与延伸",
}


def _title_suffix_for_angle(*, digest_mode: str, angle: ChapterAngleSpec) -> str:
    mapping = SPRINT_TITLE_SUFFIXES if _normalize_digest_mode(digest_mode) == "sprint" else SYSTEMATIC_TITLE_SUFFIXES
    return mapping.get(angle.label, angle.label)


def _truncate_title_topic(value: str, *, fallback: str, max_length: int) -> str:
    cleaned = _clean_text(value).strip("：:，,。；; ")
    if not cleaned:
        cleaned = _clean_text(fallback).strip("：:，,。；; ")
    if not cleaned:
        return "当前主题"

    fragments = [
        _clean_text(fragment).strip("：:，,。；; ")
        for fragment in re.split(r"[：:，,。；;()（）/]", cleaned)
    ]
    for fragment in fragments:
        if 2 <= len(fragment) <= max_length and _has_cjk(fragment):
            return fragment

    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[:max_length].rstrip("：:，,。；; ")


def _build_fallback_chapter_title(
    *,
    topic: str,
    display_subject: str,
    digest_mode: str,
    angle: ChapterAngleSpec,
) -> str:
    suffix = _title_suffix_for_angle(digest_mode=digest_mode, angle=angle)
    topic_budget = max(4, 26 - len(suffix))
    title_topic = _truncate_title_topic(topic, fallback=display_subject, max_length=topic_budget)
    title = clean_generated_chapter_title(f"{title_topic}：{suffix}")
    if is_usable_resolved_chapter_title(title):
        return title

    fallback_topic = _truncate_title_topic(display_subject, fallback="当前主题", max_length=topic_budget)
    fallback_title = clean_generated_chapter_title(f"{fallback_topic}：{suffix}")
    if is_usable_resolved_chapter_title(fallback_title):
        return fallback_title

    return clean_generated_chapter_title(f"{fallback_topic}：{angle.label}")


def _title_key(value: str) -> str:
    return clean_generated_chapter_title(value).casefold()


def _split_title_components(title: str) -> tuple[str, str]:
    cleaned = clean_generated_chapter_title(title)
    for separator in ("：", ":"):
        if separator in cleaned:
            left, right = cleaned.split(separator, 1)
            return left.strip(), right.strip()
    return cleaned, ""


def _chapter_focus_candidates(chapter: PlannerChapterPlan, *, subject_display_name: str) -> list[str]:
    raw_candidates: list[str] = []
    raw_candidates.extend(list(chapter.search_queries))
    raw_candidates.extend(list(chapter.required_elements))
    raw_candidates.append(chapter.objective)
    raw_candidates.append(chapter.writing_instructions)

    candidates: list[str] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        normalized = _normalize_topic_phrase(raw, max_length=18)
        if not normalized or normalized == subject_display_name or _is_generic_topic_text(normalized):
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(normalized)
    return candidates


def _dedupe_chapter_plan_titles(
    chapter_plan: list[PlannerChapterPlan],
    *,
    subject_display_name: str,
) -> list[PlannerChapterPlan]:
    deduped: list[PlannerChapterPlan] = []
    seen_keys: set[str] = set()

    for chapter in chapter_plan:
        title = clean_generated_chapter_title(chapter.title) or f"第 {chapter.chapter_index} 章"
        if _title_key(title) in seen_keys:
            topic, suffix = _split_title_components(title)
            for focus in _chapter_focus_candidates(chapter, subject_display_name=subject_display_name):
                if focus == topic:
                    continue
                candidate = clean_generated_chapter_title(f"{focus}：{suffix}" if suffix else focus)
                if candidate and _title_key(candidate) not in seen_keys and is_usable_resolved_chapter_title(candidate):
                    title = candidate
                    break
            else:
                fallback_focus = _chapter_focus_candidates(chapter, subject_display_name=subject_display_name)
                for focus in fallback_focus:
                    candidate = clean_generated_chapter_title(f"{topic}：{focus}")
                    if candidate and _title_key(candidate) not in seen_keys and is_usable_resolved_chapter_title(candidate):
                        title = candidate
                        break
                else:
                    title = clean_generated_chapter_title(f"{topic}：专题 {chapter.chapter_index}")

        seen_keys.add(_title_key(title))
        deduped.append(chapter.model_copy(update={"title": title}))

    return deduped


def _minimal_shared_inputs(subject: str) -> SharedInputs:
    return SharedInputs(
        fast_hints=FastTopicHints(),
        subject_profile=SubjectProfile(subject_name="", subject_slug=subject),
    )


def _normalize_digest_mode(value: Any) -> str:
    default_mode = get_teaching_runtime_config().planner.default_digest_mode
    normalized = str(value or default_mode).strip().lower()
    return "sprint" if normalized == "sprint" else "systematic"


def _normalize_tone(value: Any) -> str:
    text = _clean_text(value)
    return text or get_teaching_runtime_config().planner.default_tone


def _normalize_selected_skillpacks(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    return _dedupe_strings(items, limit=16)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _strip_goal_instruction_text(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    stripped = _GOAL_PREFIX_RE.sub("", text).strip(" ：:，,。；;")
    for marker in _GENERIC_TOPIC_MARKERS:
        if marker in stripped:
            stripped = stripped.replace(marker, " ")
    stripped = re.sub(r"\s+", " ", stripped).strip(" ：:，,。；;")
    return stripped or text


def _normalize_topic_phrase(value: Any, *, max_length: int = 20) -> str:
    cleaned = _strip_goal_instruction_text(value)
    if not cleaned:
        return ""
    fragments = [
        _clean_text(fragment).strip(" ：:，,。；;")
        for fragment in re.split(r"[，。；：,.!?！？/\n()（）]", cleaned)
        if _clean_text(fragment).strip(" ：:，,。；;")
    ]
    for fragment in fragments:
        if 2 <= len(fragment) <= max_length and _has_cjk(fragment):
            return fragment
    if len(cleaned) <= max_length and _has_cjk(cleaned):
        return cleaned
    return cleaned[:max_length].rstrip(" ：:，,。；;")


def _is_generic_topic_text(value: Any) -> bool:
    text = _clean_text(value)
    if not text:
        return True
    return any(marker in text for marker in _GENERIC_TOPIC_MARKERS)


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


def _read_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


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
        normalized[key] = _dedupe_strings(raw.get(key) or [], limit=5) or list(fallback.get(key, []))
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
    mode_config = get_planner_mode_runtime_config(digest_mode)
    min_chapters = mode_config.min_chapters
    max_chapters = mode_config.max_chapters
    default_length = mode_config.target_length
    merged["include_exercises"] = bool(merged.get("include_exercises", True))
    merged["include_sources"] = bool(merged.get("include_sources", True))
    merged["math_mode"] = bool(merged.get("math_mode", False))
    target_count = _read_positive_int(merged.get("target_chapter_count")) or _read_positive_int(
        fallback.get("target_chapter_count")
    ) or min_chapters
    merged["min_chapters"] = min_chapters
    merged["max_chapters"] = max_chapters
    merged["target_chapter_count"] = min(max_chapters, max(min_chapters, target_count))
    merged["target_length"] = _clean_text(merged.get("target_length")) or default_length
    merged.pop("fixed_chapter_count", None)
    return merged


def _collect_topic_hints(shared_inputs: SharedInputs | None, *, limit: int = 12) -> list[str]:
    if shared_inputs is None:
        return []
    raw_topics = [
        *shared_inputs.subject_profile.key_topics,
        *shared_inputs.fast_hints.chapter_candidates,
    ]
    return _dedupe_strings(raw_topics, limit=limit)


def _estimate_target_chapter_count(
    *,
    digest_mode: str,
    shared_inputs: SharedInputs,
    user_goal: str,
    requested_count: int | None = None,
) -> int:
    normalized_mode = _normalize_digest_mode(digest_mode)
    mode_config = get_planner_mode_runtime_config(normalized_mode)
    min_chapters = mode_config.min_chapters
    max_chapters = mode_config.max_chapters
    if requested_count is not None and requested_count > 0:
        return min(max_chapters, max(min_chapters, requested_count))

    topic_count = len(_collect_topic_hints(shared_inputs, limit=12))
    goal_text = _clean_text(user_goal)
    goal_weight = sum(
        1
        for marker in ("系统", "完整", "全面", "详细", "深入", "从零", "体系", "进阶", "扩展", "考试", "真题", "冲刺")
        if marker in goal_text
    )

    if normalized_mode == "sprint":
        estimated = topic_count if topic_count > 0 else min_chapters
        if goal_weight >= 2:
            estimated += 1
        return min(max_chapters, max(min_chapters, estimated))

    estimated = topic_count if topic_count > 0 else min_chapters
    if shared_inputs.subject_profile.has_heavy_formulas:
        estimated += 1
    if shared_inputs.subject_profile.has_heavy_questions:
        estimated += 1
    if goal_weight >= 2:
        estimated += 1
    if goal_weight >= 4:
        estimated += 1
    return min(max_chapters, max(min_chapters, estimated))


def _looks_like_subject_slug(value: Any) -> bool:
    text = _clean_text(value)
    return bool(text) and bool(_SUBJECT_SLUG_RE.fullmatch(text))


def _resolve_subject_display_name(
    subject: str,
    *,
    shared_inputs: SharedInputs | None,
    user_goal: str = "",
) -> str:
    profile_name = _normalize_topic_phrase(shared_inputs.subject_profile.subject_name if shared_inputs else "")
    if profile_name and not _looks_like_subject_slug(profile_name):
        return profile_name

    if shared_inputs is not None:
        for candidate in [
            *shared_inputs.subject_profile.key_topics,
            *shared_inputs.fast_hints.chapter_candidates,
        ]:
            cleaned = _normalize_topic_phrase(candidate)
            if cleaned and not _looks_like_subject_slug(cleaned):
                return cleaned

    goal = _normalize_topic_phrase(user_goal)
    if goal and not _looks_like_subject_slug(goal):
        if len(goal) <= 20 and not _is_generic_topic_text(goal):
            return goal
        goal_head = _normalize_topic_phrase(re.split(r"[，。；：,.!?！？\n]", goal, maxsplit=1)[0].strip())
        if goal_head and len(goal_head) <= 20:
            return goal_head

    normalized_subject = _normalize_topic_phrase(subject)
    if normalized_subject and not _looks_like_subject_slug(normalized_subject):
        return normalized_subject
    return "当前主题"


def _replace_subject_slug_text(value: Any, replacement: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    return _SUBJECT_SLUG_INLINE_RE.sub(replacement, text)


def _extract_goal_topic_hints(user_goal: str, *, display_subject: str) -> list[str]:
    fragments = [
        _normalize_topic_phrase(fragment)
        for fragment in _TOPIC_SPLIT_RE.split(_replace_subject_slug_text(user_goal, display_subject))
        if _normalize_topic_phrase(fragment)
    ]
    hints: list[str] = []
    for fragment in fragments:
        if (
            fragment == display_subject
            or len(fragment) < 2
            or len(fragment) > 20
            or not _has_cjk(fragment)
            or _is_generic_topic_text(fragment)
        ):
            continue
        hints.append(fragment)
    return _dedupe_strings(hints, limit=4)


def _angle_specs_for_mode(digest_mode: str) -> list[ChapterAngleSpec]:
    return SPRINT_ANGLE_SPECS if _normalize_digest_mode(digest_mode) == "sprint" else SYSTEMATIC_ANGLE_SPECS


def _topic_candidates(*, subject: str, shared_inputs: SharedInputs, user_goal: str) -> list[str]:
    display_subject = _resolve_subject_display_name(subject, shared_inputs=shared_inputs, user_goal=user_goal)
    return _dedupe_strings(
        [
            *[_normalize_topic_phrase(item) for item in _collect_topic_hints(shared_inputs, limit=12)],
            *_extract_goal_topic_hints(user_goal, display_subject=display_subject),
            display_subject,
        ],
        limit=12,
    )


def _build_topic_sequence(topics: list[str], *, display_subject: str, target_count: int) -> list[tuple[str, bool]]:
    seeds = topics or [display_subject]
    return [
        (seeds[index] if index < len(seeds) else seeds[index % len(seeds)], index >= len(seeds))
        for index in range(target_count)
    ]


def _build_search_queries(
    *,
    subject: str,
    display_subject: str,
    topic: str,
    angle: ChapterAngleSpec,
) -> list[str]:
    query_subject = _clean_text(subject)
    query_topic = _clean_text(topic) or display_subject
    base_subject = query_subject if query_subject and not _looks_like_subject_slug(query_subject) else display_subject
    return _dedupe_strings(
        [f"{base_subject} {query_topic} {suffix}" for suffix in angle.query_suffixes],
        limit=4,
    )


def _build_media_hints(topic: str, angle: ChapterAngleSpec) -> dict[str, list[str]]:
    cleaned_topic = _clean_text(topic) or "当前主题"
    return {
        "images": [f"{cleaned_topic} 的{angle.label}示意图"],
        "mermaid": [f"{cleaned_topic} 的{angle.label}关系图"],
        "interactive": [],
    }


def _build_fallback_chapter_plan(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    shared_inputs: SharedInputs,
    target_count: int,
) -> list[PlannerChapterPlan]:
    display_subject = _resolve_subject_display_name(subject, shared_inputs=shared_inputs, user_goal=user_goal)
    topic_sequence = _build_topic_sequence(
        _topic_candidates(subject=subject, shared_inputs=shared_inputs, user_goal=user_goal),
        display_subject=display_subject,
        target_count=target_count,
    )
    angle_specs = _angle_specs_for_mode(digest_mode)
    chapter_plan: list[PlannerChapterPlan] = []

    for index, (topic, _repeated_topic) in enumerate(topic_sequence, start=1):
        angle = angle_specs[(index - 1) % len(angle_specs)]
        chapter_plan.append(
            PlannerChapterPlan(
                chapter_index=index,
                title=_build_fallback_chapter_title(
                    topic=topic,
                    display_subject=display_subject,
                    digest_mode=digest_mode,
                    angle=angle,
                ),
                objective=angle.objective_template.format(topic=topic or display_subject),
                required_elements=list(angle.required_elements),
                search_queries=_build_search_queries(
                    subject=subject,
                    display_subject=display_subject,
                    topic=topic,
                    angle=angle,
                ),
                writing_instructions=angle.writing_instruction,
                media_hints=_build_media_hints(topic, angle),
            )
        )
    return chapter_plan


def _build_build_constraints(
    *,
    digest_mode: str,
    target_count: int,
    shared_inputs: SharedInputs,
) -> dict[str, Any]:
    normalized_mode = _normalize_digest_mode(digest_mode)
    mode_config = get_planner_mode_runtime_config(normalized_mode)
    if normalized_mode == "sprint":
        return {
            "min_chapters": mode_config.min_chapters,
            "max_chapters": mode_config.max_chapters,
            "target_chapter_count": min(mode_config.max_chapters, max(mode_config.min_chapters, target_count)),
            "include_exercises": True,
            "include_sources": True,
            "math_mode": shared_inputs.subject_profile.has_heavy_formulas,
            "target_length": mode_config.target_length,
        }
    return {
        "min_chapters": mode_config.min_chapters,
        "max_chapters": mode_config.max_chapters,
        "target_chapter_count": min(mode_config.max_chapters, max(mode_config.min_chapters, target_count)),
        "include_exercises": True,
        "include_sources": True,
        "math_mode": shared_inputs.subject_profile.has_heavy_formulas,
        "target_length": mode_config.target_length,
    }


def _build_plan_summary(display_subject: str, *, digest_mode: str, chapter_count: int) -> str:
    if _normalize_digest_mode(digest_mode) == "sprint":
        return (
            f"围绕 {display_subject} 生成一份冲刺型知识文档，按当前主题密度组织约 {chapter_count} 章内容，"
            "优先覆盖考点、题型、易错点和最后复盘抓手。"
        )
    return (
        f"围绕 {display_subject} 生成一份系统型知识文档，按主题依赖组织约 {chapter_count} 章内容，"
        "逐步展开概念、方法、应用、辨析与综合迁移。"
    )


def build_fallback_plan(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    tone: str,
    shared_inputs: SharedInputs,
    selected_skillpacks: list[str] | None = None,
    target_count: int | None = None,
) -> BuildPlannerDraft:
    normalized_mode = _normalize_digest_mode(digest_mode)
    normalized_tone = _normalize_tone(tone)
    display_subject = _resolve_subject_display_name(subject, shared_inputs=shared_inputs, user_goal=user_goal)
    resolved_count = _estimate_target_chapter_count(
        digest_mode=normalized_mode,
        shared_inputs=shared_inputs,
        user_goal=user_goal,
        requested_count=target_count,
    )
    chapter_plan = _build_fallback_chapter_plan(
        subject=subject,
        user_goal=user_goal,
        digest_mode=normalized_mode,
        shared_inputs=shared_inputs,
        target_count=resolved_count,
    )
    chapter_plan = _dedupe_chapter_plan_titles(
        chapter_plan,
        subject_display_name=display_subject,
    )
    research_queries = _dedupe_strings(
        [query for chapter in chapter_plan for query in chapter.search_queries],
        limit=24,
    )
    settings = get_settings()
    return BuildPlannerDraft(
        subject=display_subject,
        user_goal=user_goal,
        digest_mode=normalized_mode,
        tone=normalized_tone,
        selected_skillpacks=_normalize_selected_skillpacks(selected_skillpacks),
        chapter_plan=chapter_plan,
        research_queries=research_queries,
        media_plan={
            "enable_mermaid": settings.mermaid_generation_enabled,
            "enable_images": settings.image_generation_enabled,
            "enable_interactive_html": False,
        },
        build_constraints=_build_build_constraints(
            digest_mode=normalized_mode,
            target_count=resolved_count,
            shared_inputs=shared_inputs,
        ),
        plan_summary=_build_plan_summary(
            display_subject,
            digest_mode=normalized_mode,
            chapter_count=resolved_count,
        ),
    )


def _merge_raw_candidates(current: Any, previous: Any) -> dict[str, Any]:
    merged = _coerce_mapping(previous)
    merged.update(_coerce_mapping(current))
    return merged


def _is_usable_provisional_title(value: Any) -> bool:
    text = _clean_text(value)
    return is_usable_resolved_chapter_title(text)


def _merge_chapter(
    *,
    current: Any,
    previous: Any,
    fallback: PlannerChapterPlan,
    subject_display_name: str,
) -> PlannerChapterPlan:
    current_raw = _coerce_mapping(current)
    previous_raw = _coerce_mapping(previous)
    merged = _merge_raw_candidates(current_raw, previous_raw)
    current_title = _replace_subject_slug_text(current_raw.get("title"), subject_display_name)
    previous_title = _replace_subject_slug_text(previous_raw.get("title"), subject_display_name)
    current_objective = _replace_subject_slug_text(current_raw.get("objective"), subject_display_name)
    previous_objective = _replace_subject_slug_text(previous_raw.get("objective"), subject_display_name)
    current_writing = _replace_subject_slug_text(current_raw.get("writing_instructions"), subject_display_name)
    previous_writing = _replace_subject_slug_text(previous_raw.get("writing_instructions"), subject_display_name)
    title = (
        _clean_text(current_title)
        if _is_usable_provisional_title(current_title)
        else _clean_text(previous_title)
        if _is_usable_provisional_title(previous_title)
        else fallback.title
    )
    objective = (
        _clean_text(current_objective)
        if _is_usable_cn_text(current_objective, min_length=6)
        else _clean_text(previous_objective)
        if _is_usable_cn_text(previous_objective, min_length=6)
        else fallback.objective
    )
    writing_instructions = (
        _clean_text(current_writing)
        if _is_usable_cn_text(current_writing, min_length=8)
        else _clean_text(previous_writing)
        if _is_usable_cn_text(previous_writing, min_length=8)
        else fallback.writing_instructions
    )
    normalized_queries = [
        _replace_subject_slug_text(item, subject_display_name)
        for item in list(merged.get("search_queries") or [])
    ]
    fallback_queries = [
        _replace_subject_slug_text(item, subject_display_name)
        for item in list(fallback.search_queries)
    ]
    return PlannerChapterPlan(
        chapter_index=fallback.chapter_index,
        title=title,
        objective=objective,
        required_elements=_normalize_required_elements(merged.get("required_elements"), fallback.required_elements),
        search_queries=_normalize_search_queries(normalized_queries, fallback_queries),
        writing_instructions=writing_instructions,
        media_hints=_normalize_media_hints(merged.get("media_hints"), fallback.media_hints),
    )


def _resolve_requested_count(
    *,
    digest_mode: str,
    shared_inputs: SharedInputs,
    user_goal: str,
    current_raw: dict[str, Any],
    previous_raw: dict[str, Any],
) -> int:
    baseline = _estimate_target_chapter_count(
        digest_mode=digest_mode,
        shared_inputs=shared_inputs,
        user_goal=user_goal,
    )
    candidates = [
        len(_coerce_chapter_mappings(current_raw.get("chapter_plan"))),
        len(_coerce_chapter_mappings(previous_raw.get("chapter_plan"))),
        _read_positive_int(_coerce_mapping(current_raw.get("build_constraints")).get("target_chapter_count")),
        _read_positive_int(_coerce_mapping(previous_raw.get("build_constraints")).get("target_chapter_count")),
    ]
    requested_count = max([baseline, *[candidate for candidate in candidates if candidate]], default=baseline)
    return _estimate_target_chapter_count(
        digest_mode=digest_mode,
        shared_inputs=shared_inputs,
        user_goal=user_goal,
        requested_count=requested_count,
    )


def _normalize_plan_summary(value: Any, fallback: str, *, subject_display_name: str) -> str:
    text = _replace_subject_slug_text(value, subject_display_name)
    if not _is_usable_cn_text(text, min_length=10):
        return fallback
    return text


def normalize_planner_draft(
    draft: BuildPlannerDraft | Mapping[str, Any] | None,
    *,
    subject: str,
    user_goal: str,
    requested_digest_mode: str,
    requested_tone: str,
    selected_skillpacks: list[str] | None = None,
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
    resolved_skillpacks = _normalize_selected_skillpacks(
        selected_skillpacks
        if selected_skillpacks is not None
        else current_raw.get("selected_skillpacks") or previous_raw.get("selected_skillpacks")
    )
    subject_display_name = _resolve_subject_display_name(subject, shared_inputs=shared, user_goal=user_goal)
    target_count = _resolve_requested_count(
        digest_mode=digest_mode,
        shared_inputs=shared,
        user_goal=user_goal,
        current_raw=current_raw,
        previous_raw=previous_raw,
    )
    fallback_plan = build_fallback_plan(
        subject=subject,
        user_goal=user_goal,
        digest_mode=digest_mode,
        tone=tone,
        shared_inputs=shared,
        selected_skillpacks=resolved_skillpacks,
        target_count=target_count,
    )
    current_chapters = _coerce_chapter_mappings(current_raw.get("chapter_plan"))
    previous_chapters = _coerce_chapter_mappings(previous_raw.get("chapter_plan"))
    chapter_plan = [
        _merge_chapter(
            current=current_chapters[index] if index < len(current_chapters) else {},
            previous=previous_chapters[index] if index < len(previous_chapters) else {},
            fallback=fallback,
            subject_display_name=subject_display_name,
        )
        for index, fallback in enumerate(fallback_plan.chapter_plan)
    ]
    chapter_plan = _dedupe_chapter_plan_titles(
        chapter_plan,
        subject_display_name=subject_display_name,
    )

    chapter_queries = [query for chapter in chapter_plan for query in chapter.search_queries]
    research_queries = _dedupe_strings(
        [
            *[_replace_subject_slug_text(item, subject_display_name) for item in list(current_raw.get("research_queries") or [])],
            *[_replace_subject_slug_text(item, subject_display_name) for item in list(previous_raw.get("research_queries") or [])],
            *chapter_queries,
        ],
        limit=24,
    )
    fallback_research_queries = [
        _replace_subject_slug_text(item, subject_display_name)
        for item in list(fallback_plan.research_queries)
    ]
    return BuildPlannerDraft(
        subject=subject_display_name,
        user_goal=user_goal,
        digest_mode=digest_mode,
        tone=tone,
        selected_skillpacks=resolved_skillpacks,
        chapter_plan=chapter_plan,
        research_queries=research_queries or fallback_research_queries,
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
            subject_display_name=subject_display_name,
        ),
    )


def normalize_planner_payload(
    payload: BuildPlannerDraft | Mapping[str, Any] | None,
    *,
    subject: str,
    user_goal: str,
    requested_digest_mode: str,
    requested_tone: str,
    selected_skillpacks: list[str] | None = None,
    shared_inputs: SharedInputs | None = None,
    latest_plan: BuildPlannerDraft | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_planner_draft(
        payload,
        subject=subject,
        user_goal=user_goal,
        requested_digest_mode=requested_digest_mode,
        requested_tone=requested_tone,
        selected_skillpacks=selected_skillpacks,
        shared_inputs=shared_inputs,
        latest_plan=latest_plan,
    ).model_dump(mode="json")


__all__ = [
    "BuildPlannerDraft",
    "PlannerChapterPlan",
    "_resolve_subject_display_name",
    "build_fallback_plan",
    "normalize_planner_draft",
    "normalize_planner_payload",
]

